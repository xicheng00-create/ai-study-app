#!/bin/bash
# launchd 自启：/Library/LaunchDaemons（开机即跑，无需登录，对齐 Design Spec F1）
# 用法: sudo launchctl load /Library/LaunchDaemons/com.aistudy.service.plist
# 本机 sudo 无 TTY，用 osascript 弹 GUI 密码框（见 memory 教训）
LABEL="com.aistudy.service"
REPO="/Users/xicheng/WorkBuddy/AI学习小组app"
PLIST="/Library/LaunchDaemons/${LABEL}.plist"

cat > "/tmp/${LABEL}.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key><string>${LABEL}</string>
	<key>ProgramArguments</key>
	<array>
		<string>/bin/bash</string>
		<string>${REPO}/deploy/run.sh</string>
	</array>
	<key>WorkingDirectory</key><string>${REPO}</string>
	<key>RunAtLoad</key><true/>
	<key>KeepAlive</key><true/>
	<key>StandardOutPath</key><string>${REPO}/logs/service.log</string>
	<key>StandardErrorPath</key><string>${REPO}/logs/service.err.log</string>
	<key>EnvironmentVariables</key>
	<dict>
		<key>PATH</key><string>/Users/xicheng/.workbuddy/binaries/python/versions/3.13.12/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
	</dict>
</dict>
</plist>
PLIST

echo "plist written to /tmp/${LABEL}.plist"
echo "安装到 /Library/LaunchDaemons 需 root，用 osascript 弹密码框："
echo "osascript -e 'do shell script \"cp /tmp/${LABEL}.plist ${PLIST} && launchctl unload ${PLIST} 2>/dev/null; launchctl load ${PLIST}\" with administrator privileges'"
