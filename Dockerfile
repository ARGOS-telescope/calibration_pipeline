FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Base system deps
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    ca-certificates \
    bzip2 \
    git \
  && rm -rf /var/lib/apt/lists/*

## Install micromamba (multi-arch, lightweight)
RUN set -eux; \
  arch=$(uname -m); \
  if [ "$arch" = "x86_64" ]; then mm_arch="linux-64"; \
  elif [ "$arch" = "aarch64" ] || [ "$arch" = "arm64" ]; then mm_arch="linux-aarch64"; \
  else echo "Unsupported architecture: $arch"; exit 1; fi; \
  url="https://micro.mamba.pm/api/micromamba/${mm_arch}/latest"; \
  echo "Installing micromamba from $url"; \
  mkdir -p /usr/local/bin; \
  curl -fsSL --retry 5 --retry-delay 5 "$url" | tar -xvj -C /usr/local/bin --strip-components=1 bin/micromamba; \
  ln -sf /usr/local/bin/micromamba /usr/local/bin/conda || true
ENV MAMBA_ROOT_PREFIX=/opt/conda
ENV PATH=/opt/conda/bin:/usr/local/bin:$PATH

# Create CASA environment and install modular CASA packages (see CASAdocs Modular Packages)
# Note: casadata is not installed by pip; mount it at $CASADATA or add later as needed
ENV CASADATA=/opt/casadata
RUN micromamba create -y -p /opt/conda/envs/casa python=3.12 \
  && micromamba run -p /opt/conda/envs/casa pip install --upgrade pip wheel \
  && micromamba run -p /opt/conda/envs/casa pip install \
       casaconfig==1.4.0 \
       casatools==6.7.2.42 \
       casatasks==6.7.2.42 \
       casaplotms==2.7.4 \
       casashell==6.7.2.42 \
       casaplotserver==2.0.3 \
       casatestutils==6.7.2.42 \
       casatablebrowser==0.0.39 \
       casalogger==1.0.23 \
       casafeather==0.0.27 \
       casampi==0.5.9 \
       h5py==3.15.1

# Pre-populate CASA external data (measures, geodetic, ephemerides) for runtime
ENV CASADATA=/root/.casa/data
RUN mkdir -p /root/.casa/data \
  && chown -R root:root /root/.casa \
  && micromamba run -p /opt/conda/envs/casa python - <<'PY'
from casaconfig.private.data_update import data_update
data_update('/root/.casa/data', logger=None, auto_update_rules=True, verbose=True)
PY

## Auto-activate the 'casa' env for all interactive shells (micromamba hook)
RUN echo 'eval "$(/usr/local/bin/micromamba shell hook -s bash)"' >> /etc/bash.bashrc \
  && echo "micromamba activate /opt/conda/envs/casa" >> /etc/bash.bashrc

# Ensure subsequent RUN commands execute in login shell with conda available
SHELL ["/bin/bash", "-lc"]

WORKDIR /workspace

# Include the calibration script in the image
COPY basic_calibration.py /workspace/basic_calibration.py

# Default to an interactive shell; env auto-activates via bashrc
CMD ["bash"]


