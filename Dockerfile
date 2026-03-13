FROM ubuntu:22.04

# 1. தேவையான மென்பொருட்களை நிறுவுதல்
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    ttyd \
    bash \
    openssh-client \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# 2. வேலை செய்யும் கோப்புறை
WORKDIR /home

# 3. Port-ஐத் திறத்தல் (Render போன்ற தளங்களுக்குத் தேவை)
EXPOSE 7860

# 4. நேரடியாக Ping மற்றும் ttyd-ஐ இயக்குதல்
# இங்கே 'ttyd' உங்கள் மெயின் பிராசஸாக இருக்கும். 
# பின்னணியில் (Background) ping ஓடிக்கொண்டே இருக்கும்.
CMD sh -c "while true; do ping -c 1 remote-cmd.onrender.com; sleep 120; done & ttyd -p 7860 bash"

