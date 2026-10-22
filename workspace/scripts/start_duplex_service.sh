#!/usr/bin/env bash
# 一键启动 Qwen3-Omni duplex 三阶段后端 + realtime_web UI，自动挑选空闲 GPU，
# 失败自动重试，最后打印可直接在浏览器打开的访问地址。
# VAD：  DEPLOY_CONFIG=workspace/configs/demo_vad.json bash workspace/scripts/start_duplex_service.sh
# 用法：bash /mnt/geminihzceph/user_whynotzhliu/Omni/workspace/scripts/start_duplex_service.sh
# 可以在任意目录下执行，脚本会自己 cd 到项目根目录。
#
# 关键坑点（踩过才知道）：
# 1. 必须 cd 到项目根目录再用相对路径的 --deploy-config，否则从别的目录调用
#    会报 "Deploy config not found"。
# 2. `vllm serve` 会 fork 出 VLLM::StageEngineCoreProc_* 子进程；如果只
#    `kill -9` 外层壳进程，子进程会变成孤儿继续占着整张 GPU 不放——这正是
#    之前反复出现"显存被别的任务占满"假象的真正根因。本脚本用 `set -m`
#    让每个后台任务都是独立进程组，重试/清理时向进程组发送 TERM。

set -uo pipefail
set -m   # 开启 job control：每个后台任务独立成一个进程组，方便整组 kill 干净

PROJECT_ROOT="$(dirname "${BASH_SOURCE[0]}")/../.."
cd "$PROJECT_ROOT" || exit 1
PROJECT_ROOT="$(pwd)"

MODEL="${MODEL:-../modelbase/Omni/Qwen3-Omni-30B-A3B-Instruct}"
DEPLOY_CONFIG="${DEPLOY_CONFIG:-vllm-omni/vllm_omni/deploy/qwen3_omni_duplex.yaml}"
QWEN_GPUS="${QWEN_GPUS:-}"
VLLM_PORT="${VLLM_PORT:-8092}"
UI_PORT="${UI_PORT:-7865}"
MAX_ATTEMPTS=2
READY_TIMEOUT=3000  # 秒，单次尝试等三阶段就绪的最长时间（30B MoE thinker 的
                    # torch.compile + CUDA Graph 预热实测需要远超5分钟，5分钟
                    # 会在权重刚加载完、还没编译完时就被误杀）
GPU_FREE_THRESHOLD_MIB=1000

# 防止同一台机器上同时跑两份实例：之前就因为一个后台任务还在跑、又手动起了一次，
# 两边抢同一个硬编码端口 8092 和相近的 master-port，互相打架导致反复失败。
LOCK_FILE=/tmp/start_duplex_service.lock
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "检测到已有一份 start_duplex_service.sh 在运行（锁文件 $LOCK_FILE），为避免抢 GPU/端口，本次退出。" >&2
  echo "如需确认，请用 ps aux | grep start_duplex_service 查看正在跑的实例。" >&2
  exit 1
fi

LOG_DIR="workspace/logs/$(date +%Y%m%d_%H%M%S)_duplex_service"
mkdir -p "$LOG_DIR"

# 必须在 conda activate 之前就把 curl 的绝对路径固定下来：omni 环境的 bin 目录
# 下没有 curl，conda activate 切换 PATH 后 curl 会直接变成 "not found"（被脚本
# 里的 2>/dev/null 悄悄吞掉），导致就绪检测永远失败，白白等满超时后把明明已经
# 启动成功的后端当成“失败”误杀掉——这是实测踩过的坑。
CURL_BIN="$(command -v curl)"
if [ -z "$CURL_BIN" ]; then
  echo "找不到 curl，无法做就绪检测" >&2
  exit 1
fi

# shellcheck disable=SC1091
. "${OMNI_CONDA_ACTIVATE:-../my_envs/miniconda3/bin/activate}"
conda activate "${OMNI_CONDA_ENV:-omni}"

if [ -n "$QWEN_GPUS" ]; then
  python -c 'import sys; from vllm_omni.config.stage_config import load_deploy_config; c=load_deploy_config(sys.argv[1]); assert all(str(s.devices)=="0" for s in c.stages), "显式 GPU 分配要求各阶段 devices=0"' "$DEPLOY_CONFIG" || exit 1
fi

export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1}"
export no_proxy="${no_proxy:-localhost,127.0.0.1}"

log() { echo "[$(date +%H:%M:%S)] $*"; }

free_gpus() {
  nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
    | awk -F',' -v th="$GPU_FREE_THRESHOLD_MIB" '{gsub(/ /,"",$2); if ($2+0 < th) print $1}'
}

# 杀掉一个后台任务及其全部子进程（靠 set -m 保证的独立进程组）
kill_group() {
  local pid="$1"
  [ -n "$pid" ] || return 0
  kill -TERM -- "-$pid" 2>/dev/null
}

cleanup_on_exit() {
  kill_group "${pid0:-}"; kill_group "${pid1:-}"; kill_group "${pid2:-}"
}
trap cleanup_on_exit EXIT INT TERM

ready=0
for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  master_port=$((26000 + attempt * 100))

  mapfile -t free < <(free_gpus)
  if [ "${#free[@]}" -lt 3 ]; then
    log "尝试 $attempt：空闲 GPU 不足 3 张（当前空闲：${free[*]:-无}），等待 15s 后重查"
    sleep 15
    continue
  fi
  if [ -n "$QWEN_GPUS" ]; then
    IFS=',' read -r g0 g1 g2 extra <<< "$QWEN_GPUS"
    if [ -z "${g2:-}" ] || [ -n "${extra:-}" ] || [ "$g0" = "$g1" ] || [ "$g0" = "$g2" ] || [ "$g1" = "$g2" ]; then
      log "QWEN_GPUS 必须是三个互不相同的 GPU，例如 4,5,6"
      exit 1
    fi
    for gpu in "$g0" "$g1" "$g2"; do
      if [[ ! " ${free[*]} " =~ " $gpu " ]]; then
        log "指定 GPU$gpu 不空闲，拒绝启动"
        exit 1
      fi
    done
  else
    g0=${free[0]}; g1=${free[1]}; g2=${free[2]}
  fi
  log "尝试 $attempt：thinker=GPU$g0 talker=GPU$g1 code2wav=GPU$g2 master-port=$master_port"

  CUDA_VISIBLE_DEVICES=$g0 vllm serve "$MODEL" --omni --port "$VLLM_PORT" --stage-id 0 \
    --omni-master-address 127.0.0.1 --omni-master-port "$master_port" \
    --deploy-config "$DEPLOY_CONFIG" --init-timeout 1800 --stage-init-timeout 1800 \
    > "$LOG_DIR/stage0_attempt${attempt}.log" 2>&1 &
  pid0=$!
  CUDA_VISIBLE_DEVICES=$g1 vllm serve "$MODEL" --omni --stage-id 1 --headless \
    --omni-master-address 127.0.0.1 --omni-master-port "$master_port" \
    --deploy-config "$DEPLOY_CONFIG" --stage-init-timeout 1800 \
    > "$LOG_DIR/stage1_attempt${attempt}.log" 2>&1 &
  pid1=$!
  CUDA_VISIBLE_DEVICES=$g2 vllm serve "$MODEL" --omni --stage-id 2 --headless \
    --omni-master-address 127.0.0.1 --omni-master-port "$master_port" \
    --deploy-config "$DEPLOY_CONFIG" --stage-init-timeout 1800 \
    > "$LOG_DIR/stage2_attempt${attempt}.log" 2>&1 &
  pid2=$!

  attempt_ok=0
  steps=$((READY_TIMEOUT / 5))
  for ((i = 1; i <= steps; i++)); do
    if ! kill -0 "$pid0" 2>/dev/null || ! kill -0 "$pid1" 2>/dev/null || ! kill -0 "$pid2" 2>/dev/null; then
      log "尝试 $attempt：有阶段进程提前退出，本轮失败"
      break
    fi
    if "$CURL_BIN" -s --noproxy '*' -m 2 "http://127.0.0.1:${VLLM_PORT}/v1/models" 2>/dev/null | grep -q '"object":"list"'; then
      attempt_ok=1
      break
    fi
    sleep 5
  done

  if [ "$attempt_ok" -eq 1 ]; then
    log "尝试 $attempt：后端三阶段就绪"
    ready=1
    break
  fi

  log "尝试 $attempt：超时或失败，连同子进程一起清理后重试"
  kill_group "$pid0"; kill_group "$pid1"; kill_group "$pid2"
  sleep 3
done

if [ "$ready" -ne 1 ]; then
  log "后端在 $MAX_ATTEMPTS 次尝试后仍未就绪，放弃。日志见 $LOG_DIR"
  exit 1
fi

log "启动 realtime_web UI（端口 $UI_PORT）"
UI_MODEL="$(realpath "$MODEL")"
(
  cd vllm-omni/examples/online_serving/realtime_web
  python server.py --port "$UI_PORT" --profile qwen3-turn --vad --model "$UI_MODEL" \
    --ws-backend "ws://127.0.0.1:${VLLM_PORT}" \
    > "$PROJECT_ROOT/$LOG_DIR/ui.log" 2>&1 &
  echo $! > "$PROJECT_ROOT/$LOG_DIR/ui.pid"
)

ui_ready=0
for i in $(seq 1 30); do
  if "$CURL_BIN" -s --noproxy '*' -m 2 "http://127.0.0.1:${UI_PORT}/healthz" >/dev/null 2>&1; then
    ui_ready=1
    break
  fi
  sleep 2
done

if [ "$ui_ready" -ne 1 ]; then
  log "UI 没能在 60s 内就绪，查看日志：$LOG_DIR/ui.log"
  exit 1
fi

# 服务已就绪：取消 EXIT 清理 trap，不然脚本退出时会把刚起好的后端杀掉
trap - EXIT INT TERM

echo
echo "=========================================="
echo "服务已全部就绪"
echo "本机访问：http://127.0.0.1:${UI_PORT}/"
if [ -n "${VSCODE_PROXY_URI:-}" ]; then
  public_url=$(echo "$VSCODE_PROXY_URI" | sed "s/{{port}}/${UI_PORT}/")
  echo "浏览器访问（末尾斜杠不可省）：${public_url}/"
fi
echo "日志目录：$LOG_DIR"
echo "=========================================="
