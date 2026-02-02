# NekoFlare

基于上置信界（Upper Confidence Bound, UCB）算法的轻量级 Cloudflare IP 优选工具。

## 项目简介

NekoFlare 是一个用于自动化筛选 Cloudflare 优质边缘节点的 Python 脚本。与传统的暴力扫描工具不同，本项目引入了强化学习中的多臂老虎机（Multi-Armed Bandit）模型，通过 UCB 算法在“探索”（Exploration）与“利用”（Exploitation）之间取得平衡。

程序能够根据历史网络表现（延迟与吞吐量），动态调整对不同 IP 网段的扫描权重。随着运行次数的积累，算法将自动收敛至当前网络环境下表现最优的网段，同时保持一定的随机探索能力以适应网络波动。

**注意**：本程序设计初衷仅为辅助更新本地 hosts 文件以优化连接体验。

---

## LEGAL DISCLAIMER AND WARNING

**PLEASE READ THIS SECTION CAREFULLY BEFORE USING THE SOFTWARE.**

This software (`app.py` and associated files) is provided "AS IS", without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and non-infringement.

**1. Permitted Use:**
This tool is designed exclusively for local network optimization based on local `hosts` configuration. It is intended to help users identify optimal connection endpoints within their own network environment.

**2. Compliance with Laws and Terms:**
Users must strictly adhere to Cloudflare's Terms of Service and all applicable local, state, national, and international laws and regulations. You are solely responsible for ensuring that your use of this software does not violate any third-party rights or applicable terms of service.

**3. Prohibited Activities:**
The use of this software for any illegal purpose is strictly prohibited. This includes, but is not limited to:
*   Unauthorized scanning or probing of networks.
*   Denial-of-service attacks.
*   Bypassing access controls or censorship circumvention in violation of local laws.
*   Any activity that disrupts or interferes with the integrity or performance of Cloudflare's services.

**4. Limitation of Liability:**
The author (ccbkkb) and contributors assume **NO RESPONSIBILITY OR LIABILITY** for any consequences resulting from the use or misuse of this software. This includes, but is not limited to:
*   Termination of service or account bans by Cloudflare or ISPs.
*   Legal actions taken by third parties or government agencies.
*   Data loss or system instability.

**BY USING THIS SOFTWARE, YOU ACKNOWLEDGE THAT YOU HAVE READ THIS DISCLAIMER AND AGREE TO ASSUME ALL RISKS ASSOCIATED WITH ITS USE.**

---

## 核心算法

### UCB 调度模型 (Version 5.2)
程序维护一个状态模型，记录各 /24 子网的历史奖励值。评分公式如下：

$$ Score = \bar{X}_j + C \cdot \sqrt{\frac{2 \ln n}{n_j}} $$

其中 $\bar{X}_j$ 为该子网的平均效用（由 TCP 延迟和 HTTP 下载速度加权计算），后一项为置信区间上界，用于驱动算法探索未知或少测的网段。

### 冷启动保护 (Cold Start)
为防止模型在数据稀疏阶段陷入局部最优，程序内置冷启动机制：
*   当程序启动次数少于 4 次，或历史有效样本不足时，将自动忽略模型权重。
*   在此阶段，程序强制执行全量随机普查模式，以确保初始数据的广度。

## 环境要求

*   **Python**: 3.6 或更高版本
*   **依赖库**: 仅使用 Python 标准库，无需安装任何第三方 pip 包。
    *   `os`, `sys`, `json`, `math`, `socket`, `time`, `random`, `argparse`, `ipaddress`, `urllib`, `concurrent.futures`

## 使用说明

### 1. 启动程序
直接运行脚本即可开始优选：

```bash
python3 app.py
```

### 2. 命令行参数

*   `--fix_conf`: 若配置文件损坏，使用此参数重置为默认配置。
*   `--ipv6 [mode]`: 控制 IPv6 扫描行为。
    *   不加参数: 默认仅扫描 IPv4。
    *   `--ipv6`: 同时扫描 IPv4 和 IPv6。
    *   `--ipv6 only`: 仅扫描 IPv6。

示例：
```bash
# 仅扫描 IPv6 地址
python3 app.py --ipv6 only
```

## 配置说明

首次运行后，程序会在当前目录生成 `config.json`。主要配置项如下：

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `threads` | 500 | TCP 扫描阶段的并发线程数。 |
| `timeout` | 1.0 | TCP 连接超时时间（秒）。 |
| `test_count` | 10000 | 每次运行生成的扫描目标 IP 总数。 |
| `port` | 443 | 目标端口。 |
| `speed_test_range` | 20 | 从 TCP 扫描结果中选取延迟最低的前 N 个 IP 进行测速。 |
| `min_speed_target` | 5.0 | 结果筛选阈值（MB/s），低于此速度的 IP 不会被标记为优选。 |
| `decay_rate` | 0.85 | 历史数据衰减系数。数值越小，模型越倾向于遗忘旧数据。 |

## 输出文件

*   `ucb_model.json`: 存储算法权重的核心数据文件。
*   `result.csv`: 单次运行的最终优选结果（CSV 格式），包含 IP、延迟和下载速度。
*   `trace.log`: 运行日志。
*   `ipv4.txt` / `ipv6.txt`: 缓存的 Cloudflare IP 范围列表。
