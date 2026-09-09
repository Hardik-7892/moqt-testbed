# VM Setup Guide — MoQT Testbed

> For the Ubuntu 24.04 VM running inside VirtualBox.
> Written from actual installation experience on 2026-07-27.

---

## 1. Mount the shared folder

If using VirtualBox shared folders (Windows host → Linux guest):

1. In VirtualBox Manager, select VM → Settings → Shared Folders → Add
   - Folder Path: `C:\projects\moq-testbed`
   - Folder Name: `moq-testbed`
   - Auto-mount: ✅, Make Permanent: ✅

2. In the VM:

```bash
sudo mkdir -p /mnt/moq-testbed
sudo mount -t vboxsf moq-testbed /mnt/moq-testbed
sudo usermod -aG vboxsf $USER
```

3. Log out and back in (or run `newgrp vboxsf`), then:

```bash
ln -s /mnt/moq-testbed ~/moq-testbed
```

> **Note:** If files in the shared folder have Windows line endings (`\r\n`), fix them:
> ```bash
> find /mnt/moq-testbed -name "*.sh" -exec sed -i 's/\r$//' {} +
> ```

---

## 2. Install system packages

### 2.1 Everything available via apt

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv python3-dev python3-wheel \
    build-essential net-tools help2man python3-iptables \
    docker.io docker-compose-v2 \
    golang-go
```

> **Note:** `docker.io` is the Ubuntu package name for Docker Engine (the name `docker` was taken by a KDE widget years ago). Same software.

> **Note:** `golang-go` was missing a dependency (`golang-1.26-go`) on some Ubuntu versions — if it fails, install Go from the official tarball instead:
> ```bash
> wget https://go.dev/dl/go1.22.5.linux-amd64.tar.gz
> sudo rm -rf /usr/local/go
> sudo tar -C /usr/local -xzf go1.22.5.linux-amd64.tar.gz
> echo 'export PATH=$PATH:/usr/local/go/bin' >> ~/.bashrc
> source ~/.bashrc
> ```

### 2.2 Add user to docker group

```bash
sudo usermod -aG docker $USER
```

Then log out and back in (or run `newgrp docker` to start the group in the current session).

### 2.3 Do NOT install from apt

| Package | Reason |
|---------|--------|
| `rustup` | Conflicts with `cargo` (which is already installed) |
| `mininet` via pip | Use Containernet source instead (step 3) |

---

## 3. Install Containernet

Containernet extends Mininet with Docker support. It's not in apt, so build from source.

```bash
cd ~
git clone https://github.com/containernet/containernet.git
cd containernet
```

### 3.1 Fix the examples symlink bug

Ubuntu 24.04+ has an issue where `mininet/examples` might be a broken symlink containing `../examples`. This causes `pip install` to fail with `"supposed package directory 'mininet/examples' exists, but is not a directory"`.

Fix: delete the file and create it as a real directory:

```bash
rm -f mininet/examples
mkdir mininet/examples
```

### 3.2 Install

```bash
sudo make install
```

> If this fails with `ModuleNotFoundError: No module named 'iptc'`, install the missing package:
> ```bash
> sudo apt install -y python3-iptables help2man
> ```
> Then retry `sudo make install`.

> If this fails with `"externally-managed-environment"` (PEP 668), use the `--break-system-packages` flag:
> ```bash
> sudo python3 -m pip install --break-system-packages .
> ```

### 3.3 Verify

```bash
python3 -c "from mininet.net import Containernet; print('Containernet OK')"
```

### 3.4 Clean up source

The source directory is no longer needed after install:

```bash
cd ~ && rm -rf containernet
```

---

## 4. Install Python dependencies for the testbed

```bash
cd ~/moq-testbed
pip3 install --break-system-packages -r requirements.txt
```

> The `--break-system-packages` flag is needed on Ubuntu 24.04+ due to PEP 668 (externally-managed environment protection).

---

## 5. Verify everything

```bash
echo "=== Docker ===" && docker --version
echo "=== Compose ===" && docker compose version
echo "=== Go ===" && go version
echo "=== Python ===" && python3 --version
echo "=== Containernet ===" && python3 -c "from mininet.net import Containernet; print('OK')"
echo "=== PyYAML ===" && python3 -c "import yaml; print('OK')"
```

Expected output:

```
=== Docker ===
Docker version 29.1.3, build 29.1.3-0ubuntu4.1
=== Compose ===
Docker Compose version 2.40.3+ds1-0ubuntu1
=== Go ===
go version go1.26.0 linux/amd64
=== Python ===
Python 3.14.4
=== Containernet ===
Containernet OK
=== PyYAML ===
OK
```

---

## 6. Build Docker images

```bash
cd ~/moq-testbed
make build-all
```

This builds Docker images for all 5 core implementations:
- `moq-rs/relay:18` and `moq-rs/client:18` (Cloudflare)
- `moxygen/relay:14/16/18` and `moxygen/client:14/16/18` (Meta)
- `imquic/relay:16/17/18` and `imquic/cli:16/17/18` (Meetecho)
- `moqtail/relay:16` and `moqtail/client:16` (OzU)
- `moq-dev/relay:latest` and `moq-dev/cli:latest` (kixelated)

---

## Troubleshooting

### Pip keeps failing with "externally-managed-environment"

Create a config file to disable PEP 668 permanently:

```bash
mkdir -p ~/.config/pip
echo "[global]" > ~/.config/pip/pip.conf
echo "break-system-packages = true" >> ~/.config/pip/pip.conf
```

Then pip commands should work without the `--break-system-packages` flag.

### Docker fails to run without sudo

Make sure your user is in the `docker` group and you've logged out and back in:

```bash
sudo usermod -aG docker $USER
# Then log out completely and back in
# Verify with: groups
```

### Containernet `make install` fails on `examples` directory

See step 3.1 — delete the broken symlink and create a real directory.

### `apt install docker.io` fails on containerd dependency

This was a transient issue with the Ubuntu 24.04 repo. If it persists, install Docker from the official repo:

```bash
sudo apt remove -y docker.io docker-compose-v2 2>/dev/null
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-v2
```
