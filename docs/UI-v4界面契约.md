# UI v4 实施契约（2026-10-21）
用户已批准正式制作，并删除顶部品牌组合。仅外壳视觉和保活适配，不改业务接口/坐标/路网/渲染器。
父文档单一聊天、地图实例。海报同源 iframe 首次按需加载，随后只隐藏。父级负责原 refreshState 到点消费。
postMessage 协议 qixi-ui-v1：子→父 ready/request-state/busy/back；父→子 snapshot/active/epoch/unavailable。校验 origin、source、sid；只传 generation、visited、epoch，不传照片和密钥。
子页按 generation+epoch 幂等失效旧任务；ready 后取得最新快照，storage 使用同一入口。切换仅 fitStage/invalidateSize，不重发模型请求。
跨目录版本更新 app/ui_version.py、runtime.py 与 main.py 的应用元数据。海报 renderer、配色、业务数据不变。
