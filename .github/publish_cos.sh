#!/usr/bin/env bash
# Mirror verified release assets to Tencent COS through its S3-compatible API,
# then read every file back anonymously, as students' copies will.
#
#   publish_cos.sh <assets-dir> <version> [root]
#
# Files go to <root>/v<version>/<name>; latest-signed.json also goes to
# <root>/update-channel/, last, so the channel never names a missing file.
# Needs COS_SECRET_ID, COS_SECRET_KEY, COS_BUCKET and COS_REGION. The upload
# key may only write under releases/; the bucket policy allows anonymous reads
# there and nothing else.
set -euo pipefail

dir=$1
version=$2
root=${3:-releases}
: "${COS_SECRET_ID:?}" "${COS_SECRET_KEY:?}" "${COS_BUCKET:?}" "${COS_REGION:?}"

export AWS_ACCESS_KEY_ID=$COS_SECRET_ID AWS_SECRET_ACCESS_KEY=$COS_SECRET_KEY AWS_DEFAULT_REGION=$COS_REGION
# COS rejects the CRC checksums newer AWS CLIs add by default.
export AWS_REQUEST_CHECKSUM_CALCULATION=when_required AWS_RESPONSE_CHECKSUM_VALIDATION=when_required
# COS refuses path-style requests; address the bucket as <bucket>.cos.<region>.
# From GitHub's US runners, parallel multipart parts to Shanghai are each slow
# enough for COS to drop them (UserNetworkTooSlow): send each file in one PUT.
AWS_CONFIG_FILE=$(mktemp)
export AWS_CONFIG_FILE
printf '[default]\ns3 =\n    addressing_style = virtual\n    multipart_threshold = 100MB\n    max_concurrent_requests = 1\n' > "$AWS_CONFIG_FILE"
# Upload through COS global acceleration (enabled on the bucket): a direct
# upload from GitHub's US runners to Shanghai did not finish 45 MB in 10 min.
# Students still download from the regional domain below.
endpoint="https://cos.accelerate.myqcloud.com"
public="https://$COS_BUCKET.cos.$COS_REGION.myqcloud.com"

upload() {  # <file> <key> [extra aws args]
  local file=$1 key=$2
  shift 2
  for attempt in 1 2 3; do
    aws s3 cp --only-show-errors --endpoint-url "$endpoint" "$@" "$file" "s3://$COS_BUCKET/$key" && return
    echo "retrying $key ($attempt)" >&2
    sleep $((attempt * 10))
  done
  return 1
}

verify() {  # <file> <key>
  local copy
  copy=$(mktemp)
  curl --fail --silent --show-error --proto '=https' --retry 3 --output "$copy" "$public/$2"
  cmp "$1" "$copy"
  rm -f "$copy"
  echo "PASS: $public/$2"
}

keys=()
for file in "$dir"/*; do
  key="$root/v$version/$(basename "$file")"
  upload "$file" "$key"
  keys+=("$file" "$key")
done
if [ -f "$dir/latest-signed.json" ]; then
  key="$root/update-channel/latest-signed.json"
  upload "$dir/latest-signed.json" "$key" --content-type application/json --cache-control no-cache
  keys+=("$dir/latest-signed.json" "$key")
fi
for ((i = 0; i < ${#keys[@]}; i += 2)); do
  verify "${keys[i]}" "${keys[i + 1]}"
done
