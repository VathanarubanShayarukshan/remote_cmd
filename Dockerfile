FROM ubuntu:22.04

# மென்பொருட்களை நிறுவுதல்
ENV DEBIAN_FRONTEND=noninteractive
RUN apt update && apt install -y \
    ttyd \
    bash \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# வேலை செய்யும் கோப்புறை
WORKDIR /home

#ping script install 
RUN apt-get install -y iputils-ping

#ping
CMD while true; do ping -c 1 remote-cmd.onrender.com; sleep 120; done

# Port-ஐத் திறத்தல்
EXPOSE 7860

# ஸ்கிரிப்டை இயக்குதல்
CMD ["./entrypoint.sh"]
