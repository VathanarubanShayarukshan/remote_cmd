#!/bin/bash

# 1. SSH அமைப்புகளை உருவாக்குதல்
mkdir -p /root/.ssh
# நீங்கள் கொடுத்த Private Key-ஐ இங்கே சேர்க்கிறோம்
cat <<EOF > /root/.ssh/id_ed25519
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACBcUnZ1EuBVb+Rsdxy7MkaOfI5J6RXS2dpptQF0YGXo0wAAAJh2hYPmdoWD
5gAAAAtzc2gtZWQyNTUxOQAAACBcUnZ1EuBVb+Rsdxy7MkaOfI5J6RXS2dpptQF0YGXo0w
AAAECHk7hTLbwxrQoYs8qL9Q+Yln0//joi6K+eBIY1M710AlxSdnUS4FVv5Gx3HLsyRo58
jknpFdLZ2mm1AXRgZejTAAAAFHJlbmRlci1kb2NrZXItYmFja3VwAQ==
-----END OPENSSH PRIVATE KEY-----
EOF

# சரியான அனுமதிகளை வழங்குதல் (Permissions)
chmod 600 /root/.ssh/id_ed25519
ssh-keyscan github.com >> /root/.ssh/known_hosts

# 2. Git அமைப்புகள் (உங்கள் பெயர் மற்றும் மின்னஞ்சலை இங்கே மாற்றவும்)
git config --global user.email "shairu2012@gamil.com"
git config --global user.name "VathanarubanShayarukshan"
git config --global --add safe.directory /home

# 3. SSH URL மூலம் Repo-வை இணைத்தல்
# முக்கியம்: 'your-username/your-repo' என்பதை உங்கள் GitHub URL-க்கு ஏற்ப மாற்றவும்
GIT_REPO="https://github.com/VathanarubanShayarukshan/data.git"

if [ ! -d ".git" ]; then
    echo "Cloning repository..."
    git clone $GIT_REPO .
else
    echo "Pulling latest changes..."
    git pull origin main
fi

# 4. பின்னணியில் தரவுகளைச் சேமிக்கும் லூப் (Auto-backup every 10 mins)
(
while true; do
  sleep 600
  git add .
  git commit -m "Auto-backup: $(date)"
  git push origin main
  echo "Backup completed at $(date)"
done
) &

# 5. Terminal-ஐ இயக்குதல்
echo "Starting Terminal at port 7860..."
ttyd -p 7860 bash
