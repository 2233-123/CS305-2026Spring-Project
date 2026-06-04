"""Sync project to VM via SFTP."""
import paramiko
import os

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.56.101", username="mininet", password="mininet", timeout=10)

# Add .local/bin to PATH
stdin, stdout, stderr = c.exec_command(
    "echo 'export PATH=$HOME/.local/bin:$PATH' >> ~/.bashrc && "
    "export PATH=$HOME/.local/bin:$PATH && "
    "which osken-manager", timeout=5)
print("osken path:", stdout.read().decode().strip())

# Copy project files
sftp = c.open_sftp()
src_dir = "C:/Users/wozai/Desktop/CS305-2026Spring-Project"
dst_dir = "/home/mininet/CS305-2026Spring-Project"

count = 0
for root, dirs, files in os.walk(src_dir):
    rel_path = os.path.relpath(root, src_dir)
    remote_dir = dst_dir
    if rel_path != ".":
        remote_dir = dst_dir + "/" + rel_path.replace("\\", "/")
    try:
        sftp.mkdir(remote_dir)
    except Exception:
        pass
    for f in files:
        local_file = root + "/" + f
        remote_file = remote_dir + "/" + f
        try:
            sftp.put(local_file, remote_file)
            count += 1
        except Exception as e:
            print("  Skip", f, ":", e)

sftp.close()
print(f"Synced {count} files")

# Verify
stdin, stdout, stderr = c.exec_command(
    "export PATH=$HOME/.local/bin:$PATH && "
    "cd ~/CS305-2026Spring-Project && "
    "ls *.py && osken-manager --version 2>&1", timeout=5)
print(stdout.read().decode())

c.close()
print("Done!")
