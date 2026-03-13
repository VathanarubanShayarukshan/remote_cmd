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

#ping script
RUN ping remote-cmd.onrender.com
# Port-ஐத் திறத்தல்
EXPOSE 7860

# ஸ்கிரிப்டை இயக்குதல்
CMD ["./entrypoint.sh"]
