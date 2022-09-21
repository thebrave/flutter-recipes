#!/bin/bash

set -e

# Writes a line of text to the log prefixed with a timestamp.
function log() {
  local text="$1"
  local now=($(date +%s) $(date +%N))
  local elapsed=$(( (now[0] - START[0]) * 1000 + (10#${now[1]} - 10#${START[1]}) / 1000000 ))
  local sec=$(( elapsed / 1000 ))
  local millis=$(( elapsed - sec * 1000 ))

  printf "[HOST][%04d.%03d] %s\\n" "${sec}" "${millis}" "${text}"
}

function ssh_to_guest() {
  local command="${1}"
  log "Execute "${command}" on target via ssh"

  local result=0
  local attempt=0
  local total_attempts=2

  while [[ ${attempt} -lt ${total_attempts} ]]; do
    attempt=$(($attempt+1))
    ssh localhost -p "${SSH_PORT}" -F "${SSH_CONFIG}" -i "${SSH_KEY}" "${command}" && return
    ssh_result=$?
    if [[ ${ssh_result} == 255 ]]; then
      log "SSH command '$command' failed with exit code ${ssh_result}. Retrying..."
      sleep 2
      continue
    fi
    log "ssh exited with exit code ${ssh_result}."
    return ${ssh_result}
  done

  log "ssh failed to connect after ${total_attempts} retries."
  return 255
}

# Scans ports from and return the first identified unused port.
function find_unused_tcp_port {
  local server_port=$1
  while ss -latn | grep -q :${server_port} && server_port < 59759; do
    server_port=$((${server_port} + 1))
  done
  echo $server_port
}

# Default values of arguments
VDL_LOCATION="device_launcher"
EMULATOR_LOG="raw_emulator.log"
SYSLOG="syslog.log"
SYMBOLIZER_CMD=""
SSH_CONFIG="ssh_config"
SSH_KEY="id_ed25519"
TEST_SUITE=""
TEST_COMMAND=""
VDL_ARGS=()

for arg in "$@"; do
    if [[ "$#" > 0 ]]; then
      case $1 in
        -v*|--vdl=*)
        VDL_LOCATION="${arg#*=}"
        ;;
        -c=*|--ssh_config=*)
        SSH_CONFIG="${arg#*=}"
        ;;
        -k=*|--ssh_key=*)
        SSH_KEY="${arg#*=}"
        ;;
        -l|--emulator_log)
        EMULATOR_LOG="${2}"
        shift
        ;;
        -s|--syslog)
        SYSLOG="${2}"
        shift
        ;;
        --symbolizer_cmd=*)
        SYMBOLIZER_CMD="${arg#*=}"
        ;;
        --test_suite=*)
        TEST_SUITE="${arg#*=}"
        ;;
        --test_command=*)
        TEST_COMMAND="${arg#*=}"
        ;;
        *)
        VDL_ARGS+=("${arg}")
        ;;
      esac
      shift
    fi
done

log "VDL Location: ${VDL_LOCATION}"
log "Symbolizer Command: ${SYMBOLIZER_CMD}"
log "VDL Args: ${VDL_ARGS[@]}"
log "TEST_SUITE: ${TEST_SUITE}"
log "TEST_COMMAND: ${TEST_COMMAND}"

# Note: This permission is required to SSH
chmod 600 ${SSH_KEY}
SSH_PORT=$(find_unused_tcp_port 32761)
GRPC_PORT=$(find_unused_tcp_port "$(($SSH_PORT + 1))")
log "SSH_PORT: ${SSH_PORT}"
log "GRPC_PORT: ${GRPC_PORT}"
log "EMULATOR_LOG: ${EMULATOR_LOG}"
log "SYSLOG: ${SYSLOG}"

readonly PORT_MAP="hostfwd=tcp::${SSH_PORT}-:22"
readonly VDL_PROTO=$(mktemp -p "${PWD}")

set +e

shutdown() {
  # Make sure --action=kill gets called even if --action=start errored.
  # Stop the emulator
  log "Stopping virtual device."
  "./${VDL_LOCATION}" \
    --action=kill \
    --ga=true \
    --launched_virtual_device_proto="${VDL_PROTO}"

  VDL_STOP_EXIT_CODE=$?

  if [[ ${VDL_STOP_EXIT_CODE} == 0 ]]; then
    log "Stopped virtual device."
  else
    log "Stopping virutal device errored, this is usually fine. Exit code ${VDL_STOP_EXIT_CODE}"
  fi
}
trap shutdown EXIT

log "Launching virtual device using VDL."
"./${VDL_LOCATION}" "${VDL_ARGS[@]}" \
  --action=start \
  --ga=true \
  --event_action="flutter_infra" \
  --host_port_map="${PORT_MAP}" \
  --output_launched_device_proto="${VDL_PROTO}" \
  --grpc_port="${GRPC_PORT}" > "${EMULATOR_LOG}"

_LAUNCH_EXIT_CODE=$?
_TEST_EXIT_CODE=0

if [[ ${_LAUNCH_EXIT_CODE} == 0 ]]; then
  log "Successfully launched virtual device proto ${VDL_PROTO}"
  # SYMBOLIZER_CMD could contain arguments so don't quote it.
  ssh_to_guest "log_listener" | ${SYMBOLIZER_CMD} >"${SYSLOG}" 2>&1 &

  ssh_to_guest "${TEST_COMMAND}"
  _TEST_EXIT_CODE=$?
else
  log "Failed to launch virtual device. Exit code ${_LAUNCH_EXIT_CODE}"
  exit 1
fi

if [[ ${_TEST_EXIT_CODE} == 0 ]]; then
  log "Test Suite ${TEST_SUITE} Passed"
else
  log "Test Suite ${TEST_SUITE} Failed with exit code ${_TEST_EXIT_CODE}"
  exit 1
fi

exit 0
