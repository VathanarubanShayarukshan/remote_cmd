FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install ttyd and bash
RUN apt update && apt install -y ttyd bash curl

# Trick: make sure /home exists and set working directory
WORKDIR /home

# Expose the port ttyd will run on
EXPOSE 7860

# Trick: dynamically detect host IP if SPACE_HOST not set
CMD HOST_URL=${SPACE_HOST:-$(curl -s http://ifconfig.me)} && \
    echo "Your Terminal URL: http://$HOST_URL:7860" && \
    ttyd -p 7860 bash