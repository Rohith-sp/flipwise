# DT3-K: the datacentres on several laptops with k3s

Deployment stage DT3-K (PRD §13.5, D72) replaces the dropped AWS stage (D66) with something the team can carry into the review room: each virtual datacentre runs on its own laptop, Kubernetes (k3s) places and supervises them, and the scheduler on the presenting laptop reaches them over the network. It adds no research evidence. Its job is the demo (15 marks: functionality, innovation, usability) and showing that the split is real.

## What runs where, and what "GPU scheduling" means here

```
 presenting laptop (k3s server)                other laptops (k3s agents)
 ┌───────────────────────────────┐            ┌──────────────────────────┐
 │ uv run flipwise live / run    │  HTTP/JSON │ pod dc-delhi   :30101    │
 │   coordinator: event heap,    │◄──────────►│ pod dc-mumbai  :30102    │
 │   simulated clock, policies,  │  NodePorts │ ...                      │
 │   planner, dashboard :8100    │            │ (flipwise-dc image only) │
 └───────────────────────────────┘            └──────────────────────────┘
```

- **Flipwise schedules the GPU jobs** (simulated Alibaba jobs with GPU, CPU and memory requests). Each datacentre pod holds one site's capacity, queue and running set and runs dispatch at the simulated time the coordinator sends (PRD §13.5). This is the same code as DT1 and DT2.
- **Kubernetes schedules the datacentres**: which laptop hosts which site (node labels), restarts, health and the network between them.
- No job runs on a real GPU. The laptops have no datacentre GPUs, and letting Kubernetes run real pods per job would make runs depend on wall-clock timing. That would break R-SIM-1 and R-DEP-1 (byte-identical outputs) and the fair policy comparison (§14.2). The coordinator keeps the simulated clock, so the outputs from five laptops are byte-identical to an in-process run.

## Data on the presenting laptop

The 5-site live demo (`--config configs/regions5.yaml`) reads `data/processed/`, which is never committed: copy it from a teammate who has it (checksums are in `data/manifests/`; run `uv run flipwise validate --config configs/regions5.yaml` after copying). Datacentre laptops never need data. Without data, every stage below still works with the 6-job toy scenario on three sites, replacing the live command with:

```bash
uv run flipwise live --mode remote --scenario tests/fixtures/toy --speed 120 --dc-urls http://<host>:30101,http://<host>:30102,http://<host>:30103
```

(in K0 use ports 8101–8103). `k3s_check.sh` uses only the toy.

## Stages

Do them in order. Each one rehearses the next, and K0 is the fallback on the day if the network fails.

| Stage | Where | Needs | Proves |
|---|---|---|---|
| K0 | 1 laptop, several terminals | nothing new | the live demo with five separate datacentre processes |
| K1 | 1 laptop, k3d (k3s nodes as containers) | Docker, k3d, kubectl, ~0.5 GB disk | the k8s manifests, labels and checks, before touching other machines |
| K2 | 2–5 laptops, k3s | Linux on each datacentre laptop, one Wi-Fi/hotspot | the real split: R-DEP-1 on the toy, R-DEP-3, the live demo across machines |
| K3 | the review | K2 twice, plus a backup recording | a calm demo |

### K0: one laptop, several terminals (no Kubernetes)

Five terminals, one per datacentre, then one for the scheduler. The `uv run` commands are the same on Linux and PowerShell:

```bash
uv run flipwise dc-serve --dc-id 0 --port 8101    # terminal 1: Delhi NCR
uv run flipwise dc-serve --dc-id 1 --port 8102    # terminal 2: Mumbai
uv run flipwise dc-serve --dc-id 2 --port 8103    # terminal 3: Chennai
uv run flipwise dc-serve --dc-id 3 --port 8104    # terminal 4: Kolkata
uv run flipwise dc-serve --dc-id 4 --port 8105    # terminal 5: Hyderabad
uv run flipwise live --mode remote --config configs/regions5.yaml --dc-urls http://127.0.0.1:8101,http://127.0.0.1:8102,http://127.0.0.1:8103,http://127.0.0.1:8104,http://127.0.0.1:8105
```

Open http://localhost:8100 for the scheduler and http://localhost:8101 to :8105 for each site's own dashboard. `uv run flipwise live --services local --config configs/regions5.yaml` does the same in one command. The toy needs no data: `bash scripts/local_cluster.sh --scenario tests/fixtures/toy --policy decision_flip`.

### K1: one laptop, k3d

k3d runs k3s nodes as Docker containers, so one laptop can rehearse the multi-laptop setup with the same manifests, labels and checks.

```bash
bash scripts/k3s/build_image.sh               # flipwise-dc:dev, ~180 MB, mostly the shared python:3.12-slim base
bash scripts/k3s/k3d_cluster.sh up            # one node hosts all five sites
bash scripts/k3s/k3s_check.sh                 # R-DEP-1 (toy, 7 policies), restart, R-DEP-3
uv run flipwise live --mode remote --config configs/regions5.yaml --dc-urls http://127.0.0.1:30101,http://127.0.0.1:30102,http://127.0.0.1:30103,http://127.0.0.1:30104,http://127.0.0.1:30105
bash scripts/k3s/k3d_cluster.sh down          # frees the disk again
```

`k3d_cluster.sh up --agents 2` spreads the sites over two simulated "laptops" (round-robin). Each extra k3d node keeps its own ~180 MB copy of the image, so on a nearly full disk stay at `--agents 0` or `1`.

Install, Linux: k3d is one binary (https://k3d.io). kubectl is a second binary, or use `k3s kubectl` once k3s is installed; the scripts find either, and `KUBECTL=...` overrides.

### K2: several laptops, k3s

**Network.** Put every laptop on one network that allows laptop-to-laptop traffic. A phone hotspot or a small travel router is safest, because campus Wi-Fi often blocks it (client isolation). Note each laptop's IP (`ip -4 addr`). Open these ports on every laptop:

| Port | Why |
|---|---|
| 6443/tcp | k3s API on the server laptop |
| 8472/udp | flannel VXLAN (pod network between laptops) |
| 10250/tcp | kubelet (logs, exec) |
| 30101–30105/tcp | the datacentre NodePorts |

```bash
# Fedora (firewalld)
sudo firewall-cmd --permanent --add-port=6443/tcp --add-port=8472/udp --add-port=10250/tcp --add-port=30101-30105/tcp
sudo firewall-cmd --permanent --zone=trusted --add-source=10.42.0.0/16 --add-source=10.43.0.0/16
sudo firewall-cmd --reload
# Ubuntu (ufw)
sudo ufw allow 6443/tcp && sudo ufw allow 8472/udp && sudo ufw allow 10250/tcp && sudo ufw allow 30101:30105/tcp
sudo ufw allow from 10.42.0.0/16 && sudo ufw allow from 10.43.0.0/16
```

**Server: the presenting laptop (A).** It also runs the coordinator and the live dashboard from the repo.

```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server --node-name laptop-a --node-ip <A_IP> --write-kubeconfig-mode 644 --disable traefik --disable metrics-server" sh -
sudo cat /var/lib/rancher/k3s/server/node-token      # the join token for the agents
```

**Agents: every other laptop (B, C, ...).** They need k3s and the image tarball, but not the repository or uv.

```bash
curl -sfL https://get.k3s.io | K3S_URL=https://<A_IP>:6443 K3S_TOKEN=<token> INSTALL_K3S_EXEC="agent --node-name laptop-b --node-ip <B_IP>" sh -
```

If a laptop has several network interfaces (Wi-Fi plus Docker or VPN), add `--flannel-iface <wifi-interface>` to its `INSTALL_K3S_EXEC`.

**Image on every node** (there is no registry):

```bash
bash scripts/k3s/build_image.sh --save flipwise-dc.tar.gz    # on A; the tarball is about 50–60 MB
bash scripts/k3s/load_image.sh flipwise-dc.tar.gz            # on A
gunzip -c flipwise-dc.tar.gz | sudo k3s ctr images import -  # on each agent (USB stick or scp)
```

**Place the sites, deploy and check** (all on A):

```bash
k3s kubectl get nodes                                         # all laptops Ready
bash scripts/k3s/label_sites.sh laptop-a=delhi laptop-b=mumbai,kolkata laptop-c=chennai,hyderabad
bash scripts/k3s/deploy.sh <A_IP>                             # waits, shows which pod is on which laptop
bash scripts/k3s/k3s_check.sh --host <A_IP>                   # R-DEP-1 toy, restart, R-DEP-3
uv run flipwise live --mode remote --config configs/regions5.yaml --dc-urls http://<A_IP>:30101,http://<A_IP>:30102,http://<A_IP>:30103,http://<A_IP>:30104,http://<A_IP>:30105
```

A NodePort answers on every node, so `<A_IP>` works even for sites hosted on B or C. Each laptop can open its own site's dashboard (for example http://localhost:30102 on the Mumbai laptop), which makes "this laptop is Mumbai" visible to the panel. Any number of laptops from 2 to 5 works; `label_sites.sh` only requires every site to be placed exactly once.

**Windows laptops.** k3s nodes are Linux-only. A Windows laptop can still be the presenter: run the `uv run flipwise live ... --dc-urls http://<node-ip>:3010x` command against the cluster, which works because the coordinator is plain Python. It can also host a site from a Linux VM with a bridged network adapter (untested). WSL2 behind NAT cannot join as an agent reliably.

**Remove everything afterwards:** `bash scripts/k3s/deploy.sh --delete`; then `/usr/local/bin/k3s-uninstall.sh` on A and `/usr/local/bin/k3s-agent-uninstall.sh` on each agent.

### K3: the review

1. Morning: K2 up, `k3s_check.sh` all PASS, live demo open at a calm speed (default 900).
2. Show the Overview, then a "Why this job moved" card. Then open one laptop's site dashboard and watch a job arrive there.
3. Failure story: on laptop B run `k3s kubectl -n flipwise delete pod -l flipwise.io/site=mumbai` (from A). Kubernetes starts a new pod within seconds, but it refuses work until reset (409), so the run stops with `DeploymentError` instead of carrying on with wrong state. Say why: a datacentre's state is not something to silently recreate, and determinism matters more than uptime here. Restart the live session afterwards.
4. If the network misbehaves, fall back to K0 on the presenting laptop (same dashboard, same story) or to the backup recording.

## Rules (from CLAUDE.md, unchanged)

- Deployment modes are transports, not logic: results always come from the in-process mode; k3s must reproduce them byte for byte (R-DEP-1).
- One coordinator at a time per set of datacentres. Every run starts with `/reset`, so a live session and a check run must not share the cluster at the same moment.
- Latency over Wi-Fi is far higher than on one machine (F18: ~5.5 ms per call on Windows; F20: ~0.8 ms in Docker on Linux). Report it with its host and network, never as a property of the method. The toy takes seconds; a dev week (58,454 calls) may take several minutes over Wi-Fi, so it is optional (`flipwise run --config configs/base.yaml --policy decision_flip --mode remote --dc-urls ...`, needs `data/processed` on A).
- Nothing here measures real cloud or laptop emissions: "Chennai" uses Southern-grid data whichever laptop hosts it.
