# Dựng VPS staging cho method `vps` — runbook copy-chạy (CR-STG-004)

Dành cho chủ dự án. Mỗi khối lệnh ghi rõ **chạy ở đâu**. Không có IP, tên miền hay tài khoản nào được điền sẵn: lệnh tự hỏi và lưu vào biến. Không gửi secret qua chat; secret đi thẳng từ máy vào GitHub qua `gh secret set` (đọc từ stdin/file, không in ra màn hình).

> Chạy lệnh trong **Terminal** (ứng dụng Terminal hoặc tab Terminal của Claude). Ô gõ `!` trong khung chat **không nhận** bàn phím, nên các lệnh có `read` sẽ không chạy được ở đó.

Kiến trúc đích (theo `STAGING_DEPLOYMENT.md` → *Method `vps`*): VPS Linux riêng · Docker · user `deploy` (không root) · thư mục `/srv/vip-staging` có marker `STAGING_TARGET` · PostgreSQL **16** chạy thành container `vip-staging-pg` trên mạng Docker `vip-staging` (không mở cổng ra ngoài) · Caddy lo HTTPS cho tên miền staging, chuyển vào `127.0.0.1:8000` · tường lửa chỉ mở SSH, 80, 443.

## 0. Cần có trước (ngoài máy tính)

1. Một **VPS mới, riêng cho staging**: Ubuntu 24.04 (khuyến nghị) hoặc 22.04, x86_64, ≥ 1 vCPU / 2 GB RAM. **Không** dùng VPS production.
2. Tài khoản quản trị có `sudo` (nhà cung cấp gửi, thường là `ubuntu` hoặc `root`) và IP của VPS.
3. Một **tên miền con** cho staging (ví dụ `staging-vtp.<miền-của-anh>`) đã có bản ghi **A trỏ về IP VPS**. Caddy cần bản ghi này để xin chứng chỉ HTTPS.
4. `gh` trên MacBook đã đăng nhập (`gh auth status`).

## A. LỆNH CHẠY TRÊN MACBOOK (zsh) — chuẩn bị và vào VPS

**A1. Nhập thông tin một lần** (lưu vào `~/.vip-staging-vps`, không phải secret):

```bash
printf 'IP hoặc tên máy VPS STAGING: '; read VPS_HOST; printf 'User quản trị có sudo trên VPS: '; read VPS_ADMIN; printf 'Cổng SSH (Enter = 22): '; read VPS_PORT; printf 'Tên miền staging (đã trỏ A về VPS, không cần https://): '; read STG_DOMAIN; STG_DOMAIN=${STG_DOMAIN#https://}; STG_DOMAIN=${STG_DOMAIN#http://}; STG_DOMAIN=${STG_DOMAIN%%/*}; printf 'VPS_HOST=%q\nVPS_ADMIN=%q\nVPS_PORT=%q\nSTG_DOMAIN=%q\n' "$VPS_HOST" "$VPS_ADMIN" "${VPS_PORT:-22}" "$STG_DOMAIN" > ~/.vip-staging-vps && cat ~/.vip-staging-vps
```

**A2. Tạo cặp khoá SSH riêng cho deploy** (khoá riêng ở lại MacBook, sau này đưa thẳng vào GitHub):

```bash
test -f ~/.ssh/vip_viettelpost_staging_deploy || ssh-keygen -t ed25519 -N '' -C vip-viettelpost-staging-deploy -f ~/.ssh/vip_viettelpost_staging_deploy
```

**A3. Chép khoá CÔNG KHAI lên VPS:**

```bash
source ~/.vip-staging-vps && scp -P "$VPS_PORT" ~/.ssh/vip_viettelpost_staging_deploy.pub "$VPS_ADMIN@$VPS_HOST:/tmp/vip-staging-deploy.pub"
```

**A4. Vào VPS** — dấu nhắc phải đổi sang tên VPS rồi mới làm phần B:

```bash
source ~/.vip-staging-vps && ssh -p "$VPS_PORT" "$VPS_ADMIN@$VPS_HOST"
```

## B. LỆNH CHẠY TRÊN VPS STAGING (bash, user quản trị)

**B1. Xác minh đúng máy — dừng ngay nếu đây không phải VPS staging mới:**

```bash
hostnamectl | head -n 8; . /etc/os-release; echo "OS: $PRETTY_NAME"; ip -brief -4 addr | grep -v '^lo'; echo "--- cổng đang lắng nghe:"; sudo ss -tlnpH | awk '{print $4, $6}'; echo "--- container đang chạy:"; sudo docker ps --format '{{.Names}}  {{.Image}}' 2>/dev/null || echo "(chưa có Docker)"
```

Máy staging **mới** chỉ có `sshd` (và có thể `systemd-resolve` trên `127.0.0.53`) đang lắng nghe, không có container nào. Nếu chạy lại runbook thì thêm được `vip-staging-*`, `caddy` (80/443), `docker-proxy` (`127.0.0.1:8000`). **Thấy bất kỳ dịch vụ nào khác** (nginx, apache, postgres, mysql, node, python, container lạ…) → **DỪNG, gõ `exit`** — có thể đang ở nhầm máy; các bước sau (nhất là tường lửa B5) có thể làm gián đoạn dịch vụ đó.

**B2. Cài gói:**

```bash
sudo apt-get update && sudo apt-get install -y docker.io curl ca-certificates openssl ufw && sudo systemctl enable --now docker && sudo docker version --format 'Docker {{.Server.Version}}'
```

**B3. User `deploy` (không root) + khoá SSH vừa chép lên:**

```bash
id deploy >/dev/null 2>&1 || sudo adduser --disabled-password --gecos "" deploy; sudo usermod -aG docker deploy && sudo install -d -m 700 -o deploy -g deploy /home/deploy/.ssh && sudo install -m 600 -o deploy -g deploy /tmp/vip-staging-deploy.pub /home/deploy/.ssh/authorized_keys && rm -f /tmp/vip-staging-deploy.pub && id deploy
```

Nhóm `docker` gần tương đương quyền root **trên máy này** — chấp nhận được vì máy chỉ dành cho staging.

**B4. Thư mục ứng dụng + marker staging:**

```bash
sudo install -d -m 750 -o deploy -g deploy /srv/vip-staging && sudo -u deploy sh -c "printf 'vip-viettelpost staging\n' > /srv/vip-staging/STAGING_TARGET" && sudo ls -l /srv/vip-staging && sudo cat /srv/vip-staging/STAGING_TARGET
```

**B5. Tường lửa — chỉ SSH, 80, 443** (mở cả cổng SSH đang dùng lẫn cổng trong cấu hình `sshd`, để không tự khoá mình ra ngoài):

```bash
CUR_PORT=${SSH_CONNECTION##* }; CFG_PORTS=$(sudo sshd -T 2>/dev/null | awk '/^port /{print $2}'); if [ -z "$CUR_PORT$CFG_PORTS" ]; then echo "KHÔNG xác định được cổng SSH - DỪNG, không bật tường lửa"; else for p in $CUR_PORT $CFG_PORTS; do sudo ufw allow "$p/tcp"; done; sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw --force enable && sudo ufw status; fi
```

**B6. PostgreSQL 16 riêng cho staging** (container, mật khẩu sinh ngẫu nhiên trong file quyền 600, không in ra):

```bash
sudo docker network inspect vip-staging >/dev/null 2>&1 || sudo docker network create vip-staging; sudo -u deploy sh -c 'umask 077; test -f /srv/vip-staging/pg.env || printf "POSTGRES_USER=vip_staging\nPOSTGRES_DB=vip_staging\nPOSTGRES_PASSWORD=%s\n" "$(openssl rand -hex 24)" > /srv/vip-staging/pg.env'; sudo docker inspect vip-staging-pg >/dev/null 2>&1 || sudo docker run -d --name vip-staging-pg --network vip-staging --restart unless-stopped --env-file /srv/vip-staging/pg.env -v vip-staging-pgdata:/var/lib/postgresql/data postgres:16; sleep 5; sudo docker exec vip-staging-pg postgres --version
```

Phải in `postgres (PostgreSQL) 16.x`. Container không mở cổng nào ra ngoài; ứng dụng nối tới nó bằng tên `vip-staging-pg` trên mạng `vip-staging`.

**B7. HTTPS bằng Caddy** (bản ghi A của tên miền phải trỏ về máy này trước):

```bash
read -r -p 'Tên miền staging (giống bước A1): ' STG_DOMAIN; sudo install -d -m 755 /srv/vip-staging-proxy && printf '%s {\n\treverse_proxy 127.0.0.1:8000\n}\n' "$STG_DOMAIN" | sudo tee /srv/vip-staging-proxy/Caddyfile >/dev/null && (sudo docker inspect vip-staging-caddy >/dev/null 2>&1 || sudo docker run -d --name vip-staging-caddy --restart unless-stopped --network host -v /srv/vip-staging-proxy/Caddyfile:/etc/caddy/Caddyfile:ro -v vip-staging-caddy-data:/data -v vip-staging-caddy-config:/config caddy:2) && sleep 10 && curl -s -o /dev/null -w "HTTPS %{http_code}\n" "https://$STG_DOMAIN/health"
```

Trước lần deploy đầu, `HTTPS 502` là **đúng** (chứng chỉ đã có, ứng dụng chưa chạy). Lỗi chứng chỉ/không kết nối → kiểm bản ghi A và cổng 80/443.

**B8. Kiểm tổng bằng script chỉ-đọc của repo + in vân tay host key:**

```bash
[ -n "${STG_DOMAIN:-}" ] || read -r -p 'Tên miền staging: ' STG_DOMAIN; curl -fsSL -o /tmp/check-host.sh https://raw.githubusercontent.com/thanhbn123/vip-viettelpost/develop/scripts/staging/vps/check-host.sh && sudo -u deploy bash /tmp/check-host.sh /srv/vip-staging vip-staging vip-staging-pg "https://$STG_DOMAIN"; echo "--- vân tay host key:"; ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Phải thấy `RESULT: READY for deploy method vps`. (Muốn cố định phiên bản script, thay `develop` trong URL bằng một SHA commit cụ thể của `develop`.) Ghi lại dòng vân tay `SHA256:…` để so ở bước C1. Xong thì gõ `exit` để về MacBook.

## C. LỆNH CHẠY TRÊN MACBOOK (zsh) — nối GitHub với VPS

**C1. Ghim host key + thử đăng nhập bằng user `deploy`:**

```bash
source ~/.vip-staging-vps && ssh-keyscan -p "$VPS_PORT" -t ed25519 "$VPS_HOST" 2>/dev/null > ~/.ssh/vip_viettelpost_staging_known_hosts && ssh-keygen -lf ~/.ssh/vip_viettelpost_staging_known_hosts
```

Vân tay in ra phải **trùng** dòng `SHA256:…` ở B8. Không trùng → **dừng** (có thể không phải máy của anh). B8 được đọc qua chính phiên SSH đã tin host key lần đầu ở A3/A4; muốn chắc tuyệt đối thì đối chiếu thêm với vân tay trên **bảng điều khiển/console web của nhà cung cấp VPS** (nếu có). Trùng thì:

```bash
source ~/.vip-staging-vps && ssh -i ~/.ssh/vip_viettelpost_staging_deploy -p "$VPS_PORT" -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$HOME/.ssh/vip_viettelpost_staging_known_hosts" "deploy@$VPS_HOST" 'id -un; hostname; cat /srv/vip-staging/STAGING_TARGET'
```

Phải in `deploy`, tên máy staging, và `vip-viettelpost staging`.

**C2. Secret của Environment `staging`** (giá trị đi thẳng vào GitHub, không hiện ra):

```bash
source ~/.vip-staging-vps && R=thanhbn123/vip-viettelpost && KH="$HOME/.ssh/vip_viettelpost_staging_known_hosts" && printf %s "$VPS_HOST" | gh secret set STAGING_SSH_HOST --env staging --repo $R && printf deploy | gh secret set STAGING_SSH_USER --env staging --repo $R && gh secret set STAGING_SSH_PRIVATE_KEY --env staging --repo $R < ~/.ssh/vip_viettelpost_staging_deploy && gh secret set STAGING_SSH_KNOWN_HOSTS --env staging --repo $R < "$KH"
```

```bash
source ~/.vip-staging-vps && R=thanhbn123/vip-viettelpost && DBURL=$(ssh -i ~/.ssh/vip_viettelpost_staging_deploy -p "$VPS_PORT" -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$HOME/.ssh/vip_viettelpost_staging_known_hosts" "deploy@$VPS_HOST" '. /srv/vip-staging/pg.env && printf "postgresql+psycopg://%s" "$POSTGRES_USER:$POSTGRES_PASSWORD@vip-staging-pg:5432/$POSTGRES_DB"') && [ -n "$DBURL" ] && printf %s "$DBURL" | gh secret set DATABASE_URL --env staging --repo $R; unset DBURL
```

`WEBHOOK_SHARED_SECRET` — sinh ngẫu nhiên, đưa vào GitHub **và** vào clipboard (để dán vào trình quản lý mật khẩu; cần lại khi đăng ký webhook với Viettel Post dev):

```bash
R=thanhbn123/vip-viettelpost && W=$(openssl rand -hex 32) && printf %s "$W" | gh secret set WEBHOOK_SHARED_SECRET --env staging --repo $R && printf %s "$W" | pbcopy && echo "Đã lưu vào GitHub và chép vào clipboard - dán ngay vào trình quản lý mật khẩu"; unset W
```

Dán xong thì xoá clipboard (clipboard có thể đồng bộ sang thiết bị Apple khác):

```bash
pbcopy < /dev/null
```

`API_KEYS` + `SMOKE_API_KEY` — một key `smoke` cho bước acceptance (key thô vào `SMOKE_API_KEY`, băm SHA-256 vào `API_KEYS`):

```bash
R=thanhbn123/vip-viettelpost && K=$(openssl rand -hex 32) && printf %s "$K" | gh secret set SMOKE_API_KEY --env staging --repo $R && printf 'smoke:%s' "$(printf %s "$K" | shasum -a 256 | cut -d' ' -f1)" | gh secret set API_KEYS --env staging --repo $R; unset K
```

Credential Viettel Post **môi trường development** (khi đã được VTP cấp) — lệnh tự hỏi, ký tự bị che. Dùng **một** trong hai cách:

```bash
gh secret set VTP_TOKEN --env staging --repo thanhbn123/vip-viettelpost
```

hoặc cặp `VTP_USERNAME` + `VTP_PASSWORD`:

```bash
gh secret set VTP_USERNAME --env staging --repo thanhbn123/vip-viettelpost && gh secret set VTP_PASSWORD --env staging --repo thanhbn123/vip-viettelpost
```

**C3. Variable của Environment `staging`** (không phải secret):

```bash
source ~/.vip-staging-vps && R=thanhbn123/vip-viettelpost && E=(--env staging --repo $R) && gh variable set STAGING_BASE_URL $E --body "https://$STG_DOMAIN" && gh variable set STAGING_DEPLOY_METHOD $E --body vps && gh variable set STAGING_APP_DIR $E --body /srv/vip-staging && gh variable set STAGING_DOCKER_NETWORK $E --body vip-staging && gh variable set STAGING_SSH_PORT $E --body "$VPS_PORT" && gh variable set STAGING_EXPECTED_HOSTNAME $E --body "$(ssh -i ~/.ssh/vip_viettelpost_staging_deploy -p "$VPS_PORT" -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$HOME/.ssh/vip_viettelpost_staging_known_hosts" "deploy@$VPS_HOST" hostname)"
```

Danh sách host/IP **production** để chặn nhầm (cách nhau bằng dấu phẩy; nhập tay, không ghi vào repo):

```bash
printf 'Host/IP PRODUCTION cần chặn: '; read PROD_DENY; gh variable set STAGING_HOST_DENYLIST --env staging --repo thanhbn123/vip-viettelpost --body "$PROD_DENY"
```

`VTP_E2E_SCENARIO_JSON` chỉ đặt **sau khi** chốt D-BIZ-001 (mẫu: `scripts/vtp_dev_e2e.scenario.example.json`).

**C4. Kiểm lại — chỉ tên secret, không có giá trị:**

```bash
gh secret list --env staging --repo thanhbn123/vip-viettelpost; gh variable list --env staging --repo thanhbn123/vip-viettelpost
```

## D. Sau đó

Báo Claude "đã xong phần VPS". Claude sẽ đo lại Environment (chỉ tên), rồi kích hoạt workflow `Staging` trên đúng SHA `develop` (đẩy `deploy/staging`); anh duyệt job ở Environment `staging` trên GitHub. Workflow tự: kiểm đầu vào → build ảnh đúng SHA → sao lưu + migration → chạy app, kiểm SHA → acceptance trên `https://<tên miền>`.

Việc còn lại ngoài VPS: đăng ký URL webhook `https://<tên miền>/api/v1/shipping/webhooks/viettel-post` (kèm `WEBHOOK_SHARED_SECRET`) ở phần *Cấu hình tài khoản* môi trường development trên partner Viettel Post; chốt D-BIZ-001 rồi đặt `VTP_E2E_SCENARIO_JSON`.

## Tên secret/variable (khớp code: `scripts/staging/preflight.py`, `.github/workflows/staging.yml`, `scripts/staging/methods/vps.sh`)

| Tên | Loại | Bắt buộc | Nguồn trong runbook |
|---|---|---|---|
| `DATABASE_URL` | secret | có | C2 (từ `pg.env` trên VPS) |
| `WEBHOOK_SHARED_SECRET` | secret | có | C2 |
| `API_KEYS` | secret | có | C2 |
| `SMOKE_API_KEY` | secret | có (acceptance) | C2 |
| `STAGING_SSH_HOST`, `STAGING_SSH_USER`, `STAGING_SSH_PRIVATE_KEY`, `STAGING_SSH_KNOWN_HOSTS` | secret | có (method `vps`) | C2 |
| `VTP_TOKEN` **hoặc** `VTP_USERNAME` + `VTP_PASSWORD` | secret | có cho G08 | C2 (credential VTP **development**) |
| `DATABASE_URL_PSQL` | secret | không | không cần — tự suy từ `DATABASE_URL` |
| `STAGING_BASE_URL`, `STAGING_DEPLOY_METHOD`, `STAGING_APP_DIR` | variable | có | C3 |
| `STAGING_DOCKER_NETWORK` | variable | có **với kiến trúc này** (DB ở mạng `vip-staging`) | C3 |
| `VTP_E2E_SCENARIO_JSON` | variable | có cho G08 | sau D-BIZ-001 |
| `STAGING_SSH_PORT`, `STAGING_EXPECTED_HOSTNAME`, `STAGING_HOST_DENYLIST` | variable | không (hai cái sau **nên** đặt) | C3 |
| `STAGING_APP_PORT`, `STAGING_PG_TOOLS_IMAGE` | variable | không | mặc định `8000`, `postgres:16` |

Trạng thái: runbook + `check-host.sh` là **DESIGNED/TESTED** (test với lệnh giả); chưa chạy trên VPS thật.
