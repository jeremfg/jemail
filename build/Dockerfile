FROM python:3.14-slim

# Variables available at build time
ARG SOPS_VERSION=3.9.1 \
    AGE_VERSION=1.1.1 \
    CURL_VERSION=8.14.1-2+deb13u2 \
    GIT_VERSION=1:2.47.3-0+deb13u1 \
    UNZIP_VERSION=6.0-29

# Variables available at runtime
ENV APP_DATA=/var/lib/jemail \
    PATH="/root/.local/bin:${PATH}" \
    SOPS_AGE_KEY_FILE=/root/.sops/age.txt

WORKDIR "/root"

# Install Python dependencies from requirements.txt
COPY pyproject.toml pyproject.toml

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install the following:
# - git (needed by semver.sh)
# - semver.sh for versioning support
# - SOPS
# - AGE
# - Python packages from requirements.txt
# - rclone (for cloud backup support)
#
# DL3013: Yes pip install is dynamic, but the versions really are pinned in the toml file.
# SC2046: The word splitting is intentional, pip install will receive multiple arguments
# hadolint ignore=DL3013,SC2046
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl="${CURL_VERSION}" \
    git="${GIT_VERSION}" \
    unzip="${UNZIP_VERSION}" \
    && curl -sL "https://raw.githubusercontent.com/bpkg/bpkg/master/setup.sh" | bash \
    && bpkg install -g jeremfg/semver.sh \
    && rm -f /usr/local/bin/bpkg* \
    && curl -sL -o /tmp/sops.deb "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops_${SOPS_VERSION}_amd64.deb" \
    && dpkg -i /tmp/sops.deb \
    && rm /tmp/sops.deb \
    && curl -sL -o /tmp/age.tar.gz "https://github.com/FiloSottile/age/releases/download/v${AGE_VERSION}/age-v${AGE_VERSION}-linux-amd64.tar.gz" \
    && tar -xzf /tmp/age.tar.gz -C /tmp \
    && mv /tmp/age/age /root/.local/bin/age \
    && mv /tmp/age/age-keygen /root/.local/bin/age-keygen \
    && chmod +x /root/.local/bin/age /root/.local/bin/age-keygen \
    && rm -rf /tmp/age /tmp/age.tar.gz \
    && pip install --no-cache-dir $(python -c "import tomllib; print(' '.join([dep.split()[0] if '==' in dep else dep for dep in tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']]))") \
    && rm pyproject.toml \
    && curl -sL "https://rclone.org/install.sh" | bash \
    && apt-get purge -y --auto-remove \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Mount app, data, and SOPS key at runtime
VOLUME ["/root/jemail", "/var/lib/jemail", "/root/.sops/age.txt"]

# Use entrypoint script from mounted volume to keep container alive
ENTRYPOINT ["src/entrypoint"]
