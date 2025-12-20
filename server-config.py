#!/usr/bin/env python3
"""
MCArtsAndCrafts Server Manager
Bloom.host Server Control & mrpack4server Deployment

Usage:
    python server-config.py          # Interactive menu
    python server-config.py status   # Check server status
    python server-config.py start    # Start server
    python server-config.py stop     # Stop server
    python server-config.py deploy   # Deploy mrpack4server + local.mrpack
"""

import paramiko
import os
import sys
import json
import urllib.request
from datetime import datetime
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn, TransferSpeedColumn, FileSizeColumn
from rich.table import Table
from rich.panel import Panel
from rich import box

# Initialize rich console
console = Console()

# Load .env file if it exists
def load_dotenv():
    """Load environment variables from .env file"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())

load_dotenv()

# Fix Windows console encoding issues
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    os.environ['PYTHONIOENCODING'] = 'utf-8'

# Connection details (from environment variables)
hostname = os.environ.get("SFTP_HOST", "")
port = int(os.environ.get("SFTP_PORT", "2022"))
username = os.environ.get("SFTP_USERNAME", "")
password = os.environ.get("SFTP_PASSWORD", "")

# Bloom.host Pterodactyl API settings
PTERODACTYL_API_URL = os.environ.get("PTERODACTYL_API_URL", "https://mc.bloom.host")
PTERODACTYL_API_KEY = os.environ.get("PTERODACTYL_API_KEY", "")
PTERODACTYL_SERVER_ID = os.environ.get("PTERODACTYL_SERVER_ID", "")

# Local paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MRPACK_FILE = os.path.join(SCRIPT_DIR, "local.mrpack")
MRPACK4SERVER_JAR = os.path.join(SCRIPT_DIR, "mrpack4server-0.5.0.jar")
CONFIG_DIR = os.path.join(SCRIPT_DIR, "config")


class RichProgressTracker:
    """Tracks upload progress using Rich"""
    def __init__(self, total_files=1, total_size=0):
        self.total_files = total_files
        self.total_size = total_size
        self.current_file = 0
        self.files_succeeded = 0
        self.files_failed = 0
        self.total_bytes_transferred = 0
        self.previous_file_transferred = 0

        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}", justify="right"),
            BarColumn(bar_width=None),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            "•",
            FileSizeColumn(),
            "•",
            TransferSpeedColumn(),
            "•",
            TimeRemainingColumn(),
            console=console,
            expand=True
        )

        self.overall_task_id = None
        self.current_file_task_id = None

    def __enter__(self):
        self.progress.__enter__()
        if self.total_files > 1:
            self.overall_task_id = self.progress.add_task(
                f"[cyan]Overall Progress ({self.files_succeeded + self.files_failed}/{self.total_files} files)",
                total=self.total_size
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.progress.__exit__(exc_type, exc_val, exc_tb)

    def start_file(self, filename, file_size):
        self.current_file += 1
        self.previous_file_transferred = 0

        display_name = filename
        if len(display_name) > 60:
            display_name = "..." + display_name[-57:]

        if self.current_file_task_id is not None:
            self.progress.remove_task(self.current_file_task_id)

        self.current_file_task_id = self.progress.add_task(
            f"[green]{display_name}",
            total=file_size
        )

    def update(self, transferred, total):
        if self.current_file_task_id is not None:
            self.progress.update(self.current_file_task_id, completed=transferred)

        if self.overall_task_id is not None:
            delta = transferred - self.previous_file_transferred
            if delta > 0:
                self.total_bytes_transferred += delta
                self.previous_file_transferred = transferred
                self.progress.update(
                    self.overall_task_id,
                    completed=min(self.total_bytes_transferred, self.total_size),
                    description=f"[cyan]Overall Progress ({self.files_succeeded + self.files_failed}/{self.total_files} files)"
                )

    def file_complete(self, success=True):
        if success:
            self.files_succeeded += 1
            if self.current_file_task_id is not None:
                task = self.progress.tasks[self.current_file_task_id]
                if task.completed < task.total:
                    remaining = task.total - task.completed
                    self.total_bytes_transferred += remaining
                self.progress.update(self.current_file_task_id, completed=task.total)
                self.progress.remove_task(self.current_file_task_id)
                self.current_file_task_id = None

            if self.overall_task_id is not None:
                self.progress.update(
                    self.overall_task_id,
                    completed=min(self.total_bytes_transferred, self.total_size),
                    description=f"[cyan]Overall Progress ({self.files_succeeded + self.files_failed}/{self.total_files} files)"
                )
        else:
            self.files_failed += 1
            if self.current_file_task_id is not None:
                self.progress.remove_task(self.current_file_task_id)
                self.current_file_task_id = None


def progress_callback(tracker):
    """Create a callback function for paramiko"""
    def callback(transferred, total):
        tracker.update(transferred, total)
    return callback


def check_credentials():
    """Check if credentials are configured"""
    if not hostname or not username or not password:
        console.print("[red]Error: SFTP credentials not configured![/red]")
        console.print("[yellow]Please create a .env file with:[/yellow]")
        console.print("  SFTP_HOST=your-server.bloom.host")
        console.print("  SFTP_PORT=2022")
        console.print("  SFTP_USERNAME=your-username")
        console.print("  SFTP_PASSWORD=your-password")
        console.print("  PTERODACTYL_API_KEY=your-api-key")
        console.print("  PTERODACTYL_SERVER_ID=your-server-id")
        return False
    return True


def upload_file(local_path, remote_path):
    """Upload a single file to the server"""
    if not os.path.exists(local_path):
        console.print(f"[red]Error: File not found: {local_path}[/red]")
        return False

    if not check_credentials():
        return False

    console.print(f"[cyan]Connecting to {hostname}:{port}...[/cyan]")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(hostname, port=port, username=username, password=password)
        console.print("[green]Connected![/green]")

        sftp = ssh.open_sftp()

        file_size = os.path.getsize(local_path)
        filename = os.path.basename(local_path)
        console.print(f"\n[bold]Uploading {filename} ({file_size / (1024*1024):.1f} MB)...[/bold]\n")

        with RichProgressTracker(total_files=1, total_size=file_size) as tracker:
            tracker.start_file(filename, file_size)

            try:
                callback = progress_callback(tracker)
                sftp.put(local_path, remote_path, callback=callback)
                tracker.file_complete(success=True)
                console.print(f"\n[green]✓ Upload complete![/green]")
            except Exception as e:
                tracker.file_complete(success=False)
                console.print(f"\n[red]✗ Upload failed: {e}[/red]")
                return False

        sftp.close()
        ssh.close()
        return True

    except Exception as e:
        console.print(f"\n[red]✗ Error: {e}[/red]")
        return False


def upload_directory(local_dir, remote_dir):
    """Upload a directory recursively"""
    if not os.path.exists(local_dir):
        console.print(f"[red]Error: Directory not found: {local_dir}[/red]")
        return False

    if not check_credentials():
        return False

    console.print(f"[cyan]Connecting to {hostname}:{port}...[/cyan]")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(hostname, port=port, username=username, password=password)
        console.print("[green]Connected![/green]")

        sftp = ssh.open_sftp()

        # Count files and total size
        file_count = 0
        total_size = 0
        for root, dirs, files in os.walk(local_dir):
            for file in files:
                file_path = os.path.join(root, file)
                file_count += 1
                total_size += os.path.getsize(file_path)

        console.print(f"\n[bold]Uploading {file_count} files ({total_size / (1024*1024):.1f} MB)...[/bold]\n")

        with RichProgressTracker(total_files=file_count, total_size=total_size) as tracker:
            def upload_recursive(local_path, remote_path):
                for item in os.listdir(local_path):
                    local_item = os.path.join(local_path, item)
                    remote_item = remote_path + "/" + item

                    if os.path.isfile(local_item):
                        try:
                            file_size = os.path.getsize(local_item)
                            rel_path = os.path.relpath(local_item, local_dir)
                            tracker.start_file(rel_path, file_size)
                            callback = progress_callback(tracker)
                            sftp.put(local_item, remote_item, callback=callback)
                            tracker.file_complete(success=True)
                        except Exception as e:
                            tracker.file_complete(success=False)
                            console.print(f"[red]Error uploading {item}: {e}[/red]")
                    elif os.path.isdir(local_item):
                        try:
                            sftp.mkdir(remote_item)
                        except IOError:
                            pass  # Directory exists
                        upload_recursive(local_item, remote_item)

            # Ensure remote directory exists
            try:
                sftp.mkdir(remote_dir)
            except IOError:
                pass

            upload_recursive(local_dir, remote_dir)

        console.print(f"\n[green]✓ Upload complete![/green]")

        sftp.close()
        ssh.close()
        return True

    except Exception as e:
        console.print(f"\n[red]✗ Error: {e}[/red]")
        return False


# =============================================================================
# Pterodactyl Server Control
# =============================================================================

def pterodactyl_request(endpoint, method="GET", data=None):
    """Make a request to the Pterodactyl API"""
    if not PTERODACTYL_SERVER_ID or not PTERODACTYL_API_KEY:
        console.print("[red]Error: Pterodactyl API credentials not configured![/red]")
        return None

    url = f"{PTERODACTYL_API_URL}/api/client/servers/{PTERODACTYL_SERVER_ID}{endpoint}"

    headers = {
        "Authorization": f"Bearer {PTERODACTYL_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    try:
        if data:
            data_bytes = json.dumps(data).encode('utf-8')
            req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        else:
            req = urllib.request.Request(url, headers=headers, method=method)

        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status == 204:
                return {"success": True}
            return json.loads(response.read().decode('utf-8'))

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ""
        console.print(f"[red]API Error {e.code}: {e.reason}[/red]")
        if error_body:
            console.print(f"[dim]{error_body}[/dim]")
        return None
    except urllib.error.URLError as e:
        console.print(f"[red]Connection Error: {e.reason}[/red]")
        return None
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return None


def get_server_status():
    """Get current server status"""
    result = pterodactyl_request("/resources")
    if result and "attributes" in result:
        return result["attributes"]["current_state"]
    return None


def send_power_action(action):
    """Send a power action (start, stop, restart, kill)"""
    result = pterodactyl_request("/power", method="POST", data={"signal": action})
    return result is not None


def server_start():
    """Start the server"""
    console.print("[cyan]Starting server...[/cyan]")
    if send_power_action("start"):
        console.print("[green]✓ Start signal sent[/green]")
        return True
    return False


def server_stop():
    """Stop the server"""
    console.print("[cyan]Stopping server...[/cyan]")
    if send_power_action("stop"):
        console.print("[green]✓ Stop signal sent[/green]")
        return True
    return False


def server_restart():
    """Restart the server"""
    console.print("[cyan]Restarting server...[/cyan]")
    if send_power_action("restart"):
        console.print("[green]✓ Restart signal sent[/green]")
        return True
    return False


def server_status():
    """Display current server status"""
    console.print("[cyan]Checking server status...[/cyan]")
    status = get_server_status()
    if status:
        status_colors = {
            "running": "green",
            "starting": "yellow",
            "stopping": "yellow",
            "offline": "red"
        }
        color = status_colors.get(status, "white")
        console.print(f"[bold]Server Status:[/bold] [{color}]{status.upper()}[/{color}]")
        return status
    else:
        console.print("[red]Could not retrieve server status[/red]")
        return None


def send_console_command(command):
    """Send a command to the server console"""
    url = f"{PTERODACTYL_API_URL}/api/client/servers/{PTERODACTYL_SERVER_ID}/command"

    headers = {
        "Authorization": f"Bearer {PTERODACTYL_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    try:
        data_bytes = json.dumps({"command": command}).encode('utf-8')
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=30) as response:
            return True

    except urllib.error.HTTPError as e:
        if e.code == 502:
            console.print("[yellow]Server may still be starting (502 error)[/yellow]")
        else:
            console.print(f"[red]API Error {e.code}: {e.reason}[/red]")
        return False
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return False


# =============================================================================
# Deployment Functions
# =============================================================================

def deploy_mrpack4server():
    """Deploy mrpack4server.jar and local.mrpack to the server"""
    console.print(Panel(
        "[bold]Deploying MCArtsAndCrafts to Bloom.host[/bold]\n\n"
        "This will upload:\n"
        f"  • mrpack4server-0.5.0.jar\n"
        f"  • local.mrpack\n\n"
        "[yellow]The server will auto-install mods on first start.[/yellow]",
        title="[cyan]mrpack4server Deployment[/cyan]",
        border_style="cyan"
    ))

    # Check files exist
    if not os.path.exists(MRPACK4SERVER_JAR):
        console.print(f"[red]Error: {MRPACK4SERVER_JAR} not found![/red]")
        console.print("[yellow]Download from: https://github.com/Patbox/mrpack4server/releases[/yellow]")
        return False

    if not os.path.exists(MRPACK_FILE):
        console.print(f"[red]Error: {MRPACK_FILE} not found![/red]")
        console.print("[yellow]Run: copy MCArtsAndCrafts-0.9.8.mrpack local.mrpack[/yellow]")
        return False

    console.print("\n[bold]Step 1/2: Uploading mrpack4server.jar[/bold]")
    if not upload_file(MRPACK4SERVER_JAR, "/mrpack4server-0.5.0.jar"):
        return False

    console.print("\n[bold]Step 2/2: Uploading local.mrpack[/bold]")
    if not upload_file(MRPACK_FILE, "/local.mrpack"):
        return False

    console.print("\n" + "="*50)
    console.print("[bold green]✓ Deployment complete![/bold green]")
    console.print("\n[yellow]Next steps in Bloom.host panel:[/yellow]")
    console.print("  1. Go to Startup tab")
    console.print("  2. Set Java Version to Java 21")
    console.print("  3. Set Server Jar to: mrpack4server-0.5.0.jar")
    console.print("  4. Start the server")
    console.print("="*50)

    return True


def deploy_configs():
    """Upload config directory to server"""
    console.print("[bold]Uploading config directory...[/bold]")

    if not os.path.exists(CONFIG_DIR):
        console.print(f"[yellow]No config directory found at {CONFIG_DIR}[/yellow]")
        return False

    return upload_directory(CONFIG_DIR, "/config")


def list_remote_files():
    """List files on the remote server root"""
    if not check_credentials():
        return

    console.print(f"[cyan]Connecting to {hostname}:{port}...[/cyan]")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(hostname, port=port, username=username, password=password)
        console.print("[green]Connected![/green]\n")

        sftp = ssh.open_sftp()

        files = sftp.listdir_attr("/")

        table = Table(title="Server Root Directory", box=box.ROUNDED)
        table.add_column("Name", style="cyan")
        table.add_column("Size", style="green", justify="right")
        table.add_column("Type", style="yellow")

        for f in sorted(files, key=lambda x: x.filename):
            size = f"{f.st_size / (1024*1024):.1f} MB" if f.st_size > 1024*1024 else f"{f.st_size / 1024:.1f} KB" if f.st_size > 1024 else f"{f.st_size} B"
            file_type = "DIR" if f.st_mode & 0o40000 else "FILE"
            table.add_row(f.filename, size, file_type)

        console.print(table)

        sftp.close()
        ssh.close()

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


# =============================================================================
# Interactive Menu
# =============================================================================

def interactive_menu():
    """Show an interactive menu"""
    from rich.prompt import Prompt

    while True:
        console.clear()
        console.print(Panel.fit(
            "[bold cyan]MCArtsAndCrafts Server Manager[/bold cyan]\n"
            "[dim]Bloom.host Deployment & Control[/dim]",
            border_style="cyan"
        ))

        # Show server status
        console.print()
        server_status()
        console.print()

        # Menu options
        table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
        table.add_column("Key", style="bold yellow")
        table.add_column("Action", style="white")

        table.add_row("1", "Deploy mrpack4server + modpack")
        table.add_row("2", "Upload configs only")
        table.add_row("3", "List server files")
        table.add_row("", "")
        table.add_row("4", "Start Server")
        table.add_row("5", "Stop Server")
        table.add_row("6", "Restart Server")
        table.add_row("7", "Send Console Command")
        table.add_row("", "")
        table.add_row("q", "Quit")

        console.print(table)
        console.print()

        choice = Prompt.ask("Select", choices=["1", "2", "3", "4", "5", "6", "7", "q"], default="q")

        if choice == "1":
            deploy_mrpack4server()
            Prompt.ask("\n[dim]Press Enter to continue[/dim]")

        elif choice == "2":
            deploy_configs()
            Prompt.ask("\n[dim]Press Enter to continue[/dim]")

        elif choice == "3":
            list_remote_files()
            Prompt.ask("\n[dim]Press Enter to continue[/dim]")

        elif choice == "4":
            server_start()
            Prompt.ask("\n[dim]Press Enter to continue[/dim]")

        elif choice == "5":
            server_stop()
            Prompt.ask("\n[dim]Press Enter to continue[/dim]")

        elif choice == "6":
            server_restart()
            Prompt.ask("\n[dim]Press Enter to continue[/dim]")

        elif choice == "7":
            cmd = Prompt.ask("Enter command")
            if cmd:
                if send_console_command(cmd):
                    console.print("[green]✓ Command sent[/green]")
            Prompt.ask("\n[dim]Press Enter to continue[/dim]")

        elif choice == "q":
            console.print("[dim]Goodbye![/dim]")
            break


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "deploy":
            deploy_mrpack4server()
        elif command == "configs":
            deploy_configs()
        elif command == "list":
            list_remote_files()
        elif command == "start":
            server_start()
        elif command == "stop":
            server_stop()
        elif command == "restart":
            server_restart()
        elif command == "status":
            server_status()
        elif command == "cmd" and len(sys.argv) > 2:
            cmd = " ".join(sys.argv[2:])
            console.print(f"[cyan]Sending: {cmd}[/cyan]")
            if send_console_command(cmd):
                console.print("[green]✓ Command sent[/green]")
        else:
            console.print("[yellow]Usage:[/yellow]")
            console.print("  python server-config.py          # Interactive menu")
            console.print("  python server-config.py deploy   # Deploy mrpack4server")
            console.print("  python server-config.py configs  # Upload configs")
            console.print("  python server-config.py list     # List server files")
            console.print("  python server-config.py status   # Server status")
            console.print("  python server-config.py start    # Start server")
            console.print("  python server-config.py stop     # Stop server")
            console.print("  python server-config.py restart  # Restart server")
            console.print("  python server-config.py cmd <command>  # Send command")
    else:
        interactive_menu()
