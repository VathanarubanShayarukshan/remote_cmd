FROM ubuntu:22.04

# 1. தேவையான அனைத்தையும் ஒரே RUN கட்டளையில் நிறுவுதல்
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    ttyd \
    bash \
    openssh-client \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# 2. வேலை செய்யும் கோப்புறை
WORKDIR /home

# 3. Port-ஐத் திறத்தல்
EXPOSE 7860

# Background-ல் ping ஓடவிட்டு, பிரதான ஸ்கிரிப்டை இயக்குதல்
CMD sh -c "while true; do ping -c 1 remote-cmd.onrender.com; sleep 120; done
