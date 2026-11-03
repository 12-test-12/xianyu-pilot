import os
import sys
from pathlib import Path

# CI 以 APP_ENV=test（非 dev）运行，cookie_crypto 在非 dev 环境拒绝使用默认
# 开发密钥（RuntimeError → 扫码保存/账号添加 503）。测试进程在导入 app 之前
# 注入固定强密钥，仅供本测试进程加解密往返，不用于任何生产配置。
os.environ.setdefault(
    "COOKIE_CRYPTO_SECRET",
    "xianyu-pilot-tests-cookie-secret-32chars!",
)

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))
