# AutoHDR Download cho macOS

Hai gói ứng dụng dùng chung source trong `client_source/` để giữ đồng bộ tính năng tải ảnh và xác thực license.

| Repository | Kiến trúc | Máy dùng | Runner GitHub Actions |
| --- | --- | --- | --- |
| [AutoHDR-MAC-All-M](https://github.com/mnhatt27/AutoHDR-MAC-All-M) | arm64 | Apple Silicon M1 trở lên, gồm các biến thể Pro/Max/Ultra | macos-15 |
| [AutoHDR-MAC-Intel](https://github.com/mnhatt27/AutoHDR-MAC-Intel) | x86_64 | Mac Intel 64 bit | macos-15-intel |

Ứng dụng ARM chạy native, không cần Rosetta. Gói `.app` kèm Python, Tcl/Tk và chứng chỉ CA; máy nhận không cần cài Python. Mục tiêu tối thiểu trong bundle là macOS 11.0. CI kiểm tra trên macOS 15; cần kiểm tra thêm trên máy thật trước khi cam kết hỗ trợ mọi phiên bản macOS hoặc mọi model máy.

## Đóng gói bằng GitHub Actions

1. Mở tab **Actions** của repo tương ứng, chọn **Build macOS**.
2. Chọn **Run workflow** trên nhánh `main`. Workflow cũng tự chạy khi cập nhật source.
3. Chờ bước kiểm tra, đóng gói và chạy thử `.app` hoàn tất.
4. Tải artifact `AutoHDR-macOS-arm64` hoặc `AutoHDR-macOS-x86_64` ở cuối trang run.

Workflow chọn kiến trúc theo tên hai repo ở bảng trên. Nếu dùng repo tên khác, workflow tạo cả hai bản.

Artifact gồm:

- `AutoHDR-macOS-arm64.zip` hoặc `AutoHDR-macOS-x86_64.zip`: chứa `AutoHDR.app`.
- File `.zip.sha256`: checksum của ZIP.
- `release-arm64.json` hoặc `release-x86_64.json`: metadata để cập nhật qua VPS.

Không nén trực tiếp `.app` bằng Windows: framework trong bundle có symlink và quyền executable. Script dùng `ditto` trên macOS để giữ cấu trúc đúng.

## Cài đặt trên Mac

1. Giải nén artifact tải từ GitHub, rồi giải nén ZIP ứng dụng bên trong.
2. Kéo `AutoHDR.app` vào **Applications**, sau đó mở ứng dụng.
3. Nhập license được cấp cho máy đó.

Gói hiện dùng chữ ký ad-hoc do PyInstaller tạo, chưa có Apple Developer ID/notarization. Nếu macOS chặn, sau khi thử mở app, vào **System Settings → Privacy & Security → Open Anyway** và xác nhận. Phát hành có notarization cần tài khoản/chứng chỉ Apple Developer riêng.

## Cấu hình và HWID

- Cấu hình/license lưu tại `~/Library/Application Support/AutoHDR/photoshoot_config.json`, ngoài `.app` để giữ khi thay phiên bản.
- Ảnh mặc định lưu tại `~/Downloads/AutoHDR`.
- HWID lấy từ `IOPlatformUUID`, không phụ thuộc tên máy, tài khoản, phiên bản macOS hoặc chạy qua Rosetta. License vẫn được VPS xác thực và ràng buộc theo thiết bị.
- Giao diện dùng font có sẵn trên macOS và nút Clam để hiển thị đúng trong nền tối.

## Cập nhật ứng dụng

Client Mac chỉ đọc khóa `macos.arm64` hoặc `macos.x86_64` trong phản hồi `/api/app/version`. VPS cũ chỉ có thông tin Windows vẫn dùng được cho kích hoạt/tải ảnh, và client Mac sẽ bỏ qua bản cập nhật Windows.

Để bật cập nhật Mac, người quản trị VPS:

1. Cập nhật `server.py` từ workspace AutoHDR (phần backend không đưa lên hai repo client công khai).
2. Chép hai ZIP vào `vps_server/updates/` với đúng tên artifact.
3. Giữ metadata Windows trong `version.json`, thêm object `macos`, rồi đặt nội dung `release-arm64.json` vào `macos.arm64` và `release-x86_64.json` vào `macos.x86_64`.
4. Khởi động lại server sau khi cập nhật code; metadata phiên bản được đọc lại theo mỗi request.

URL mặc định là `/api/app/download/macos/arm64` và `/api/app/download/macos/x86_64`. Có thể đổi `download_url` trong metadata thành URL HTTPS của ZIP trên nơi lưu trữ khác. Chỉ công bố metadata sau khi ZIP đã có trên server. Tăng hằng `APP_VERSION` trong `client_source/app.py` trước khi phát hành phiên bản mới.

Ứng dụng tải ZIP, đối chiếu SHA-256, kiểm tra cấu trúc `.app`, rồi hiện file trong Finder. Người dùng thoát ứng dụng và thay `.app` trong Applications. Cơ chế này giữ chữ ký bundle và không ghi đè ứng dụng đang chạy. Checksum kiểm tra tính toàn vẹn; nên dùng HTTPS cho VPS/metadata để bảo vệ việc phân phối cập nhật.

## Chạy source hoặc đóng gói trên Mac

Dùng Python 3.13 có Tcl/Tk (bản từ [python.org](https://www.python.org/downloads/macos/) hoặc bản phù hợp trong GitHub Actions).

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r MAC/requirements-build.txt
python MAC/launcher.py

# Trên Apple Silicon dùng Python ARM:
python MAC/build_mac.py --arch arm64

# Trên Intel dùng Python Intel:
python MAC/build_mac.py --arch x86_64
```

Kết quả tại `MAC/dist/<arch>/`. Script từ chối chạy trên Windows hoặc khi kiến trúc Python khác gói cần tạo.

## Kiểm tra

```sh
python -m unittest discover -s MAC/tests -v
```

CI chạy các kiểm tra này trên từng runner native, sau đó kiểm tra kiến trúc bằng `lipo`, chữ ký bundle bằng `codesign`, và khởi động binary đã đóng gói với `--smoke-test`. Chế độ này mở giao diện, thử khóa/mở nút, rồi tự thoát, không gọi VPS. Kết nối/tải ảnh với license thật cần kiểm tra riêng trên máy người dùng.

Tham khảo: [PyInstaller macOS architectures](https://pyinstaller.org/en/stable/feature-notes.html#macos-multi-arch-support), [GitHub runner images](https://github.com/actions/runner-images).
