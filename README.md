installation

`
curl -O https://raw.githubusercontent.com/VathanarubanShayarukshan/remote_cmd/refs/heads/main/setup.sh

chmod +x auto-setup.sh

# 2. Run it!
./auto-setup.sh`

Run `node server.js` only

for in bg run `nohup node server.js < /dev/null > server.log 2>&1 & disown`
