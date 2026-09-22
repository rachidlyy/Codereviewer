# Sandbox image for Python submissions.
#
# Build from the REPOSITORY ROOT, not from this directory:
#
#   docker build -f docker/runner-python/Dockerfile -t codereviewer-runner-python .
#
# The build context is the repo root because the harness is *shared* with the
# subprocess backend: there is exactly one `_runner_harness.py` in this project,
# and copying that same file into the image is what stops the two backends from
# drifting apart. If it were duplicated here instead, a fix to the subprocess
# path would silently not apply to the sandboxed one.
#
# At run time the container is started with:
#
#   --network none                 no network, so student code cannot exfiltrate
#                                  the API keys or hang on a network call
#   --memory 512m --memory-swap 512m
#   --cpus 1 --pids-limit 128      a fork bomb cannot take the machine down
#   --read-only                    the image is immutable
#   --tmpfs /work:rw,nosuid,size=128m
#                                  the one writable place, and size-capped -
#                                  on a machine where C: has hit 0 bytes free,
#                                  an unbounded write is not hypothetical
#   --user 65534:65534 --cap-drop ALL --security-opt no-new-privileges
#
# `/work` is deliberately NOT mounted `noexec`: the Java and C++ runners
# compile a binary there and have to be able to run it.

FROM python:3.12-slim

# No .pyc files. The root filesystem is read-only at run time, so a bytecode
# write would fail on every run and fill the logs with noise.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# The harness is the same file the subprocess backend executes on the host.
COPY backend/app/services/_runner_harness.py /opt/runner/harness.py
COPY docker/runner-python/entrypoint.py /opt/runner/entrypoint.py

# Created here so the image still works if the tmpfs mount is ever missing.
# The run flags mount a size-capped tmpfs over it, which is what actually
# bounds a runaway write.
RUN mkdir -p /work && chmod 1777 /work

# Nothing in here needs root, and the run flags drop to 65534 as well. Doing it
# in the image too means a plain `docker run` with no flags is still not root.
USER 65534:65534

WORKDIR /work

# `-I` is load-bearing: isolated mode ignores PYTHON* environment variables and
# the user site directory, so nothing in the environment can influence the code
# being tested.
ENTRYPOINT ["python", "-I", "/opt/runner/entrypoint.py"]
