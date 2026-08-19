import os
import subprocess
import threading

def run_command(command, cwd=None, env=None, log_callback=None):
    """
    Run a shell command and capture its output.
    """
    print(f"\n[RUNNING] {command}", flush=True)
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
        print(line, end='', flush=True)  # Hiển thị trực tiếp log ra terminal
        if log_callback:
            log_callback(line.strip())
            
    process.stdout.close()
    process.wait()
    
    return process.returncode, output_log

def execute_build(project_path, branches, env_flavor, platform, flutter_bin, appbox_cli, status_callback, final_callback=None, build_cmd_template=None):
    """
    Thực thi chuỗi lệnh build Flutter trong một thread riêng.
    status_callback(text) dùng để gửi tin nhắn cập nhật về Telegram.
    """
    try:
        # Đảm bảo branches là một list
        if isinstance(branches, str):
            branches = [branches]
            
        valid_branches = [b for b in branches if b]
        
        if not valid_branches:
            msg = "❌ Lỗi: Không có branch nào được cấu hình."
            if final_callback: final_callback(msg)
            else: status_callback(msg)
            return

        branch_names = [b.get("name") if isinstance(b, dict) else b for b in valid_branches]
        branch_text = ", ".join(branch_names)
        status_callback(f"🚀 **Bắt đầu build project**\n📁 Path: `{project_path}`\n🌿 Branches: `{branch_text}`\n⚙️ Flavor: `{env_flavor}`\n📱 Platform: `{platform}`")

        # 1. Cập nhật code qua Git
        status_callback("📥 Đang cập nhật source code (Git)...")
        git_cmds = []
        
        final_project_path = project_path
        
        for branch_info in valid_branches:
            if isinstance(branch_info, dict):
                b_path = branch_info.get("path") or project_path
                b_name = branch_info.get("name")
            else:
                b_path = project_path
                b_name = branch_info
                
            final_project_path = b_path
            
            git_cmds.extend([
                ("git fetch --all", b_path),
                ("git reset --hard HEAD", b_path),
                ("git clean -fd", b_path),
                (f"git checkout {b_name}", b_path),
                ("git pull", b_path)
            ])

        for cmd, run_path in git_cmds:
            code, out = run_command(cmd, cwd=run_path)
            if code != 0:
                msg = f"❌ Lỗi Git khi chạy `{cmd}`:\n`{out[:500]}...`"
                if final_callback: final_callback(msg)
                else: status_callback(msg)
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
        cmd_prefix = f'& "{flutter_bin}"' if os.name == 'nt' else f'"{flutter_bin}"'
        
        code, out = run_command(f'{cmd_prefix} clean', cwd=project_path)
        if code != 0:
            status_callback(f"⚠️ Flutter clean có lỗi (bỏ qua):\n`{out[:200]}...`")
            
        # Clean Xcode DerivedData if platform is ipa
        if platform == "ipa" and os.name != 'nt':
            run_command('rm -rf ~/Library/Developer/Xcode/DerivedData/*', cwd=project_path)

        # 3. Flutter Build
        status_callback("📦 Đang lấy các thư viện (Pub get)...")
        code, out = run_command(f'{cmd_prefix} pub get', cwd=project_path)
        if code != 0:
            msg = f"❌ Lỗi pub get:\n`{out[:500]}...`"
            if final_callback: final_callback(msg)
            else: status_callback(msg)
            return
            
        status_callback(f"🔨 Đang biên dịch mã nguồn ({platform} - {env_flavor}). Quá trình này có thể mất vài phút...")
        
        # Build command logic
        if build_cmd_template:
            # Thay thế lệnh flutter bằng flutter_bin của hệ thống
            if build_cmd_template.startswith("flutter "):
                build_cmd = f'{cmd_prefix} ' + build_cmd_template[8:]
            else:
                build_cmd = build_cmd_template
                
            # Thay thế các biến động nếu người dùng dùng placeholder (ví dụ: {platform})
            try:
                build_cmd = build_cmd.format(platform=platform, env_flavor=env_flavor)
            except KeyError:
                pass
        else:
            build_cmd = f'{cmd_prefix} build {platform} --flavor {env_flavor}'
            
        code, out = run_command(build_cmd, cwd=project_path)
        if code != 0:
            last_lines = "\n".join(out.splitlines()[-15:])
            msg = f"❌ Lỗi build Flutter:\n`...{last_lines}`"
            if final_callback: final_callback(msg)
            else: status_callback(msg)
            return

        # Tìm file đã build
        status_callback("✅ Build thành công! Đang chuẩn bị upload...")
        
        # Đường dẫn file build phụ thuộc vào OS/Platform (Cần cấu hình chính xác theo dự án)
        build_output_path = ""
        if platform == "apk":
            build_output_path = os.path.join(project_path, "build", "app", "outputs", "flutter-apk", f"app-{env_flavor}-release.apk")
            if not os.path.exists(build_output_path):
                build_output_path = os.path.join(project_path, "build", "app", "outputs", "flutter-apk", "app-release.apk")
        elif platform == "appbundle":
            build_output_path = os.path.join(project_path, "build", "app", "outputs", "bundle", f"{env_flavor}Release", f"app-{env_flavor}-release.aab")
            if not os.path.exists(build_output_path):
                build_output_path = os.path.join(project_path, "build", "app", "outputs", "bundle", "release", "app-release.aab")
        elif platform == "ipa":
            build_output_path = os.path.join(project_path, "build", "ios", "ipa", f"{env_flavor}.ipa") # Thay đổi tùy app
        
        # Kiểm tra nếu là file android thì ưu tiên gửi trực tiếp qua Telegram (giới hạn 2000MB nếu dùng local bot API server)
        if platform in ["apk", "appbundle"]:
            file_size_mb = os.path.getsize(build_output_path) / (1024 * 1024) if os.path.exists(build_output_path) else 0
            
            if 0 < file_size_mb <= 1999.0:
                status_callback(f"📤 File {platform.upper()} ({file_size_mb:.1f}MB) - Đang tải trực tiếp lên Telegram...")
                msg = f"🎉 **Hoàn thành quá trình build {platform.upper()}!**\n⬇️ File cài đặt của bạn ở bên dưới:"
                if final_callback: final_callback(msg, file_path=build_output_path)
                else: status_callback(msg)
                return
            elif file_size_mb > 1999.0:
                msg = f"❌ File {platform.upper()} quá lớn ({file_size_mb:.1f}MB > 2000MB giới hạn của Telegram).\n\n⚠️ Lưu ý: Appbox không hỗ trợ upload file Android (.apk, .aab) nên không thể sử dụng Appbox làm phương án dự phòng. Quá trình dừng tại đây.\n\nFile build vẫn nằm ở: `{build_output_path}`"
                if final_callback: final_callback(msg)
                else: status_callback(msg)
                return
        # 4. Upload lên Appbox
        status_callback(f"☁️ Đang upload file lên Appbox...")
        if not appbox_cli:
            msg = f"⚠️ Chưa cấu hình Appbox CLI. File build nằm tại:\n`{build_output_path}`"
            if final_callback: final_callback(msg)
            else: status_callback(msg)
            return
            
        # Lưu ý: Cần thay lệnh Appbox cho phù hợp với dự án (ví dụ upload qua curl hoặc gem appbox)
        # appbox upload path
        appbox_cmd = f'{appbox_cli} upload "{build_output_path}"'
        code, out = run_command(appbox_cmd, cwd=project_path)
        if code != 0:
            msg = f"❌ Lỗi upload Appbox:\n`{out[:500]}...`\n\nFile vẫn nằm ở: `{build_output_path}`"
            if final_callback: final_callback(msg)
            else: status_callback(msg)
            return
            
        # Parse output của Appbox để tìm link
        link = "Không tìm thấy link trong output."
        for line in out.splitlines():
            if "http" in line and "appbox" in line.lower():
                link = line.strip()
                
        msg = f"🎉 **Hoàn thành toàn bộ quy trình!**\n⬇️ **Link tải:** {link}"
        if final_callback: final_callback(msg)
        else: status_callback(msg)

    except Exception as e:
        msg = f"🔥 Lỗi hệ thống khi build: `{str(e)}`"
        if final_callback: final_callback(msg)
        else: status_callback(msg)


def start_build_thread(*args):
    """
    Bọc hàm execute_build trong 1 luồng riêng để không chặn Telegram Bot.
    """
    thread = threading.Thread(target=execute_build, args=args)
    thread.daemon = True
    thread.start()
