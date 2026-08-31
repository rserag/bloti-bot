#!/usr/bin/env bash
set -Eeuo pipefail

# shellcheck source=deploy/blotibot-deploy
source deploy/blotibot-deploy

readonly test_release=/tmp/blotibot-test-release.env
readonly test_expected_image=ghcr.io/rserag/bloti-bot@sha256:0000000000000000000000000000000000000000000000000000000000000000

compose() {
  local release_env=$1
  shift

  [[ $release_env == "$test_release" ]]
  [[ $* == "ps -q worker" ]]
  printf 'candidate-container\n'
}

docker() {
  local command=$1
  local format=$3
  local container_id=$4

  [[ $command == inspect ]]
  [[ $2 == --format ]]
  [[ $container_id == candidate-container ]]
  case $format in
    *Config.Image*) printf '%s\n' "$test_expected_image" ;;
    *State.Health*) printf 'healthy\n' ;;
    *RestartCount*) printf '0\n' ;;
    *) return 1 ;;
  esac
}

sleep() {
  :
}

verify_container "$test_release" "$test_expected_image"
