# Runbook — lịch chạy job phát lại webhook (M3)

**Trạng thái: CHƯA CÀI Ở ĐÂU.** Tài liệu này mô tả cách cài, không phải mô tả thứ đang chạy.
Không có lệnh nào trong repo tự cài nó. Mục này còn mở cho tới khi chủ dự án duyệt và cài thật.

## 1. Job này làm gì

`app.jobs.replay_webhooks` gắn lại các sự kiện webhook đã lưu nhưng chưa gắn được vào vận đơn:

- sự kiện `RECEIVED` còn sót từ trước G07;
- sự kiện `FAILED` đã hết lượt thử lại của Viettel Post (ví dụ CSDL chết lâu hơn cửa sổ thử lại);
- sự kiện `IGNORED` kèm `SHIPMENT_NOT_FOUND` mà vận đơn **nay đã có** — tình huống này xảy ra
  thật khi webhook đọc bảng `shipments` đúng lúc trước khi luồng tạo đơn kịp ghi mã vận đơn.

Chạy lại nhiều lần không sao: mỗi cặp (nhà vận chuyển, mã vận đơn) nằm trong giao dịch riêng,
sự kiện khử trùng theo dấu vân tay, dòng nào vẫn chưa có vận đơn thì giữ nguyên `IGNORED`.

## 2. Vì sao "không có lịch" là một vấn đề im lặng

Job không chạy thì **không có gì báo lỗi**. Sự kiện chỉ nằm im trong bảng, API vẫn 200, vận đơn
vẫn hiện trạng thái cũ, và không ai biết cho tới lúc có người đi đối chiếu tay.

Chỗ duy nhất nhìn thấy được là chỉ số `webhook_events_unmatched_with_shipment` ở `/metrics`
(cần API key). Nó đếm số sự kiện **đáng lẽ đã gắn được** vì vận đơn đã tồn tại. Sau mỗi lượt
chạy job, con số này phải về 0. **Nó lớn hơn 0 và không giảm nghĩa là job không chạy, hoặc đang
hỏng** — đó là tín hiệu cần theo dõi, không phải con số để ngắm.

Chỉ số này **đệm 60 giây**: `/metrics` sinh ra để bị quét liên tục, mà đây là mục duy nhất
phải hỏi CSDL, nên chi phí của nó không được tỉ lệ với tần suất quét. Một đống việc tồn
cần người xử lý thì không phải con số đổi ý nghĩa trong vòng một phút.

## 3. Cài trên máy staging (chủ dự án chạy, khi quyết định bật)

> VPS staging đang **dùng chung** với dự án khác (`READINESS_REVIEW_MAIN.md` mục 3). Tên unit
> mang tiền tố `vip-viettelpost-` để không đụng dự án khác.

Lệnh chạy nằm trong repo: `scripts/staging/vps/replay-webhooks.sh`. **Cố ý không viết thẳng
vào `ExecStart=`** — bản đầu của runbook này viết inline và nó **sai**: systemd tự khai triển
`$sha` trước khi `bash` kịp thấy, nên biến về rỗng, `--env-file` thành `/srv/vip-staging/env/.env`
và thẻ ảnh thành `vip-shipping-gateway:staging-`; unit sẽ hỏng ngay lần kích hoạt đầu tiên.
Một dòng `ExecStart` trong file Markdown thì **không có gì chạy thử nó được**; một script thì
`shellcheck` đọc được và bộ thử chạy được (`tests/unit/test_staging_replay_script.py`).

Chép script lên máy (chạy từ máy anh):

```bash
scp -i ~/.ssh/vip_viettelpost_staging_deploy \
  -o UserKnownHostsFile=~/.ssh/vip_viettelpost_staging_known_hosts \
  scripts/staging/vps/replay-webhooks.sh deploy@160.22.170.20:/srv/vip-staging/replay-webhooks.sh
ssh -i ~/.ssh/vip_viettelpost_staging_deploy \
  -o UserKnownHostsFile=~/.ssh/vip_viettelpost_staging_known_hosts \
  deploy@160.22.170.20 'chmod 755 /srv/vip-staging/replay-webhooks.sh'
```

Tạo `/etc/systemd/system/vip-viettelpost-replay.service`:

```ini
[Unit]
Description=VIP Shipping Gateway — replay stored webhook events
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
User=deploy
ExecStart=/srv/vip-staging/replay-webhooks.sh
```

Script tự kiểm trước khi chạy: có mốc `STAGING_TARGET`, `current_sha` đúng dạng 40 ký tự,
file env tồn tại và khai `APP_ENV=staging`. Thiếu bất cứ thứ nào thì **không khởi động gì cả**.

Mã thoát: `0` chạy xong và hết việc tồn; `3` chạy xong nhưng **vẫn còn** sự kiện chưa gắn —
systemd ghi unit `failed`, đó chính là lúc cần người nhìn; khác hai số đó là lượt chạy hỏng.
Không khai `SuccessExitStatus=`: `0` vốn đã là thành công, và nếu khai `3` vào đó thì đúng cái
trạng thái cần người nhìn lại trở thành "thành công" — im lặng.

Tạo `/etc/systemd/system/vip-viettelpost-replay.timer`:

```ini
[Unit]
Description=Run the webhook replay job every 15 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min
# Trễ ngẫu nhiên để không trùng đúng lúc lượt triển khai đang khởi động lại dịch vụ.
RandomizedDelaySec=120

[Install]
WantedBy=timers.target
```

Không dùng `Persistent=true`: nó chỉ có tác dụng với `OnCalendar=`, mà đây là
`OnBootSec`/`OnUnitActiveSec`. Khai vào chỉ làm người đọc tưởng có bù lượt đã lỡ.

Bật:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vip-viettelpost-replay.timer
systemctl list-timers vip-viettelpost-replay.timer
```

## 4. Nghiệm thu — và cách nghiệm thu này tự nó nói dối

Theo `CLAUDE.md` §12.1 luật 2: **chỉ được tin dấu vết do chính bộ lập lịch để lại.** Tự chạy
`ExecStart` bằng tay rồi kết luận "lịch đã chạy" là đúng kiểu sai đã dính nhiều lần.

Nghiệm thu đúng:

```bash
# 1. Lịch có thật sự kích hoạt không — xem cột LAST, không phải NEXT
systemctl list-timers vip-viettelpost-replay.timer

# 2. Lượt chạy do systemd tạo ra (không phải lượt chạy tay)
journalctl -u vip-viettelpost-replay.service --since "-2h" --no-pager

# 3. Chỉ số đã giảm về 0 chưa (cần API key)
curl -s -H "X-API-Key: <key>" https://cpn.viporder.vn/metrics \
  | python3 -c 'import json,sys; print([g for g in json.load(sys.stdin)["gauges"]])'
```

Chưa thấy đủ **cả ba**, đặc biệt là mục 2, thì chưa được ghi là đã cài xong.

## 5. Chưa làm

- Chưa cài trên máy nào. Chưa có lượt chạy tự động nào từng xảy ra.
- Chưa có cảnh báo khi chỉ số đứng cao: hiện chỉ lộ ra ở `/metrics`, phải có người hoặc hệ
  giám sát đi hỏi. Lộ ra không phải là được canh.
- Production: chưa có hợp đồng triển khai production nên chưa nói gì được về lịch bên đó.
