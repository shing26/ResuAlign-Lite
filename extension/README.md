# ResuAlign 网申回填扩展（期一 MVP）

浏览器扩展（Chrome MV3）：读取本地 ResuAlign 服务的结构化档案，在任意
网申页面**逐字段点击填充**、跳转下一个空框、实验性一键全填。
数据全程本地：档案来自本机 ResuAlign 服务，不过任何第三方服务器。

## 加载（开发者模式）

1. Chrome 打开 `chrome://extensions/`，开启右上角「开发者模式」
2. 「加载已解压的扩展程序」→ 选择本 `extension/` 目录
3. 确保本地 ResuAlign 服务运行（默认 `http://127.0.0.1:8000`）
4. 在简历中心为目标简历「生成档案」（结构化抽取）

## 使用

1. 打开任意网申页面 → 点右下角「回填」悬浮按钮
2. 先点击网页上的输入框 → 再点侧边栏里的字段 → 内容自动填入
   （React/Vue 受控表单已兼容）
3. 「跳下一个空框」顺序填写不遗漏
4. 「一键全填（实验）」按 placeholder/label 模糊匹配所有字段——
   填完请逐项核对，下拉/级联选择器尚未支持（期二）

## 架构

- `fill-core.js`：纯函数核心（平铺档案/字段匹配/受控组件赋值/跳转），
  被 content script 动态 import，并由 `tests/extension/` node 测试覆盖
- `background.js`：代理本地 API 请求（绕开页面 origin 的 CORS 限制）
- `content.js`：侧边栏 UI（Shadow DOM 隔离样式）+ DOM 操作
