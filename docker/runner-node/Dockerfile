# Sandbox image for JavaScript submissions.
#
# Build from the REPOSITORY ROOT, not from this directory:
#
#   docker build -f docker/runner-node/Dockerfile -t codereviewer-runner-node .
#
# Same reasoning as the Python image: the build context is the repo root so the
# two files copied in come from exactly one place each, and the run flags are
# identical. Node is the cheapest second language - no compile step, so it reuses
# every bit of Phase 2's plumbing.
#
# At run time the container is started with:
#
#   --network none                 no network, so student code cannot exfiltrate
#                                  the API keys or hang on a network call
#   --memory 512m --memory-swap 512m
#   --cpus 1 --pids-limit 128      a fork bomb cannot take the machine down
#   --read-only                    the image is immutable
#   --tmpfs /work:rw,nosuid,size=128m
#                                  the one writable place, and size-capped
#   --user 65534:65534 --cap-drop ALL --security-opt no-new-privileges
#
# `/work` is deliberately NOT mounted `noexec`: the Java and C++ runners
# compile a binary there and have to be able to run it.

FROM node:22-slim

# `NODE_OPTIONS` is cleared rather than merely left unset, so a future base image
# that sets it cannot inject a flag into the code being tested. The entrypoint
# also spawns each case with an explicit minimal environment, which is the
# boundary that actually matters.
ENV NODE_OPTIONS="" \
    NODE_ENV="production"

COPY docker/runner-node/harness.js /opt/runner/harness.js
COPY docker/runner-node/entrypoint.js /opt/runner/entrypoint.js

# Created here so the image still works if the tmpfs mount is ever missing.
RUN mkdir -p /work && chmod 1777 /work

# Nothing in here needs root, and the run flags drop to 65534 as well. Doing it
# in the image too means a plain `docker run` with no flags is still not root.
USER 65534:65534

WORKDIR /work

ENTRYPOINT ["node", "/opt/runner/entrypoint.js"]
