import os
import subprocess
import threading

def run_command(command, cwd=None, env=None, log_callback=None):
    """
    Run a shell command and capture its output.
    """
    if log_callback:
        log_callback(f"> {command}")
    
    # Use powershell on windows to support standard shell features if needed
    process = subprocess.Popen(
        ["powershell", "-Command", command] if os.name == 'nt' else command,
        shell=True if os.name != 'nt' else False,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    output_log = ""
    for line in iter(process.stdout.readline, ''):
        output_log += line
        if log_callback:
            log_callback(line.strip())
            
    process.stdout.close()
    process.wait()
    
    return process.returncode, output_log

def execute_build(project_path, branch, env_flavor, platform, flutter_bin, appbox_cli, status_callback):
    """
    Thực thi chuỗi lệnh build Flutter trong một thread riêng.
    status_callback(text) dùng để gửi tin nhắn cập nhật về Telegram.
    """
    try:
        status_callback(f"🚀 **Bắt đầu build project**\n📁 Path: `{project_path}`\n🌿 Branch: `{branch}`\n⚙️ Flavor: `{env_flavor}`\n📱 Platform: `{platform}`")

        # 1. Cập nhật code qua Git
        status_callback("📥 Đang cập nhật source code (Git)...")
        git_cmds = [
            "git fetch --all",
            f"git checkout {branch}",
            "git pull"
        ]
        for cmd in git_cmds:
            code, out = run_command(cmd, cwd=project_path)
            if code != 0:
                status_callback(f"❌ Lỗi Git:\n`{out[:500]}...`")
                return

        # 2. Xóa dữ liệu build cũ
        status_callback("🧹 Đang dọn dẹp dữ liệu build cũ (Clean)...")
        
        # Xóa thư mục build
        build_dir = os.path.join(project_path, "build")
        if os.name == 'nt':
            run_command(f'if (Test-Path "{build_dir}") {{ Remove-Item -Recurse -Force "{build_dir}" }}', cwd=project_path)
        else:
            run_command(f'rm -rf "{build_dir}"', cwd=project_path)

        # Flutter clean
        code, out = run_command(f'"{flutter_bin}" clean', cwd=project_path)
        if code != 0:
            status_callback(f"⚠️ Flutter clean có lỗi (bỏ qua):\n`{out[:200]}...`")
            
        # Clean Xcode DerivedData if platform is ipa
        if platform == "ipa" and os.name != 'nt':
            run_command('rm -rf ~/Library/Developer/Xcode/DerivedData/*', cwd=project_path)

        # 3. Flutter Build
        status_callback("📦 Đang lấy các thư viện (Pub get)...")
        code, out = run_command(f'"{flutter_bin}" pub get', cwd=project_path)
        if code != 0:
            status_callback(f"❌ Lỗi pub get:\n`{out[:500]}...`")
            return
            
        status_callback(f"🔨 Đang biên dịch mã nguồn ({platform} - {env_flavor}). Quá trình này có thể mất vài phút...")
        build_cmd = f'"{flutter_bin}" build {platform} --flavor {env_flavor}'
        code, out = run_command(build_cmd, cwd=project_path)
        if code != 0:
            status_callback(f"❌ Lỗi build Flutter:\n`{out[-1000:]}`")
            return

        # Tìm file đã build
        status_callback("✅ Build thành công! Đang chuẩn bị upload...")
        
        # Đường dẫn file build phụ thuộc vào OS/Platform (Cần cấu hình chính xác theo dự án)
        build_output_path = ""
        if platform == "apk":
            build_output_path = os.path.join(project_path, "build", "app", "outputs", "flutter-apk", f"app-{env_flavor}-release.apk")
        elif platform == "ipa":
            build_output_path = os.path.join(project_path, "build", "ios", "ipa", f"{env_flavor}.ipa") # Thay đổi tùy app
        
        # 4. Upload lên Appbox
        status_callback(f"☁️ Đang upload file lên Appbox...")
        if not appbox_cli:
            status_callback(f"⚠️ Chưa cấu hình Appbox CLI. File build nằm tại:\n`{build_output_path}`")
            return
            
        # Lưu ý: Cần thay lệnh Appbox cho phù hợp với dự án (ví dụ upload qua curl hoặc gem appbox)
        # appbox upload path
        appbox_cmd = f'{appbox_cli} upload "{build_output_path}"'
        code, out = run_command(appbox_cmd, cwd=project_path)
        if code != 0:
            status_callback(f"❌ Lỗi upload Appbox:\n`{out[:500]}...`\n\nFile vẫn nằm ở: `{build_output_path}`")
            return
            
        # Parse output của Appbox để tìm link
        link = "Không tìm thấy link trong output."
        for line in out.splitlines():
            if "http" in line and "appbox" in line.lower():
                link = line.strip()
                
        status_callback(f"🎉 **Hoàn thành toàn bộ quy trình!**\n⬇️ **Link tải:** {link}")

    except Exception as e:
        status_callback(f"🔥 Lỗi hệ thống khi build: `{str(e)}`")


def start_build_thread(*args):
    """
    Bọc hàm execute_build trong 1 luồng riêng để không chặn Telegram Bot.
    """
    thread = threading.Thread(target=execute_build, args=args)
    thread.daemon = True
    thread.start()
