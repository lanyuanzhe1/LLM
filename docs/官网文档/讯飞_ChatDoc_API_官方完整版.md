# 星火知识库（ChatDoc）API 官方文档

> 来源：https://www.xfyun.cn/doc/spark/ChatDoc-API.html
> 抓取时间：2026-08-28；本文件为官方页面的 Markdown 存档，仅清理了导航/图标冗余，内容未删改。
> 摘要版见同目录《讯飞_ChatDoc_API.md》。

---


## 一、服务介绍

星火知识库是基于讯飞星火大模型的知识库问答方案，能够高效检索文档信息，准确回答专业问题，为大模型补充领域知识，让大模型助你高效了解文档内容。

该接口是通过 API 的方式给开发者提供一个通用的 HTTP 接口，基于该接口，开发者可以获取开放平台的星火文档知识库问答能力，方便开发者快速集成。

### 开通授权

您可在讯飞开放平台<a href="https://console.xfyun.cn/services/aidoc" target="_blank" rel="noopener noreferrer">应用控制台</a>申请开通 API 权限并采购服务量。技术咨询可直接提交<a href="https://console.xfyun.cn/workorder/commit" target="_blank" rel="noopener noreferrer">工单</a>。

### appId 控制台

您可登录 <a href="https://chatdoc-console.xfyun.cn" target="_blank" rel="noopener noreferrer">AppId控制台</a> 管理已开通的 appId。控制台支持查看和管理 appId 下的文件、知识库、接口用量等信息，便于在 API 调用前完成资源准备，并在调用后排查文件处理状态、知识库数据和用量消耗。

### 产品体验

基于星火知识库方案 API，我们搭建了<a href="https://aiwiki.xfyun.cn" target="_blank" rel="noopener noreferrer">企业星火知识库</a>，供您快速体验功能和效果。

### 接口调用示例

部分开发语言Demo如下，其他开发语言请参照文档进行开发，欢迎大家到<a href="https://developer.xfyun.cn/" target="_blank" rel="noopener noreferrer">讯飞开放平台社区</a>交流集成经验。\

<a href="https://openres.xfyun.cn/xfyundoc/2025-03-27/5c7dc49c-f92c-4a77-9328-2a909e03df5d/1743064961791/chatdoc-api-java-demo.zip" target="_blank" rel="noopener noreferrer">星火知识库 DEMO - Java</a>

<a href="https://openres.xfyun.cn/xfyundoc/2024-08-20/e1c9e232-ee6d-495e-a3ce-af7ea60648e8/1724123967360/chatdoc-api-python-demo.zip" target="_blank" rel="noopener noreferrer">星火知识库 DEMO - Python</a>

### 接口要求

| 内容 | 说明 |
|----|----|
| 传输协议 | https |
| 接口域名 | chatdoc.xfyun.cn |
| 接口鉴权 | 签名机制，详情请参照下方[鉴权认证](#%E4%BA%8C%E3%80%81%E9%89%B4%E6%9D%83%E8%AE%A4%E8%AF%81) |
| 字符编码 | UTF-8 |
| 响应格式 | 普通接口统一采用 JSON 格式；问答接口采用 SSE 流式返回 JSON 数据帧 |
| 开发语言 | 任意，只要可以向讯飞云服务发起 HTTP/SSE 请求的均可 |
| 文档格式 | 当前支持 txt、md、doc、docx、pdf、xls、xlsx、csv、jpg、jpeg、png、bmp、ppt、pptx 格式文档 |
| 文档大小 | 不超过 20M |
| 文档长度 | 不超过 100W 字符 |

## 二、鉴权认证

在调用业务接口时，请求方需要对请求进行签名，服务端通过签名来校验请求的合法性。

### 鉴权方法

#### 1、设置签名

在 HTTP 请求头 Header 中设置参数：`appId`, `timeStamp`, `signature`。

示例：

- 文档上传接口：在 Http Request Header 中配置以下参数

``` java
String appId = "应用ID"；
String secret = "应用的秘钥"
Long timestamp = System.currentTimeMillis()/1000;
String signature = ApiAuthAlgorithm.getSignature(appId, secret, timestamp);

request.setHeader("appId",appId);
request.setHeader("timeStamp",timestamp);
request.setHeader("signature",signature);
```

- 文档问答接口：同样在 HTTP Request Header 中配置 `appId`、`timeStamp`、`signature`

``` java
https://chatdoc.xfyun.cn/openapi/v2/chat
```

签名参数说明：

| 字段名    | 类型   | 描述                                        | 必须 |
|-----------|--------|---------------------------------------------|------|
| appId     | String | 应用 ID                                     | Y    |
| timeStamp | Long   | 时间戳，单位: s，与服务端时间相差五分钟之内 | Y    |
| signature | String | 签名                                        | Y    |

#### 2、签名（signature）生成规则

- 首先，用应用 ID（appId）和时间戳（timeStamp）通过 MD5 算法生成随机授权参数 auth
- 再使用授权参数 auth 和接口密钥（secret）基于 HmacSHA1 生产签名 signature

示例：

``` java
public class ApiAuthAlgorithm {

  private static final char[] MD5_TABLE = {
    '0',
    '1',
    '2',
    '3',
    '4',
    '5',
    '6',
    '7',
    '8',
    '9',
    'a',
    'b',
    'c',
    'd',
    'e',
    'f'
  };

  /**
   * 获取签名
   *
   * @param appId    签名的key
   * @param secret 签名秘钥
   * @return 返回签名
   */
  public String getSignature(String appId, String secret, long ts) {
    try {
      String auth = md5(appId + ts);
      return hmacSHA1Encrypt(auth, secret);
    } catch (SignatureException e) {
      return null;
    }
  }

  /**
   * sha1加密
   *
   * @param encryptText 加密文本
   * @param encryptKey  加密键
   * @return 加密
   */
  private String hmacSHA1Encrypt(String encryptText, String encryptKey)
    throws SignatureException {
    byte[] rawHmac;
    try {
      byte[] data = encryptKey.getBytes(StandardCharsets.UTF_8);
      SecretKeySpec secretKey = new SecretKeySpec(data, "HmacSHA1");
      Mac mac = Mac.getInstance("HmacSHA1");
      mac.init(secretKey);
      byte[] text = encryptText.getBytes(StandardCharsets.UTF_8);
      rawHmac = mac.doFinal(text);
    } catch (InvalidKeyException e) {
      throw new SignatureException("InvalidKeyException:" + e.getMessage());
    } catch (NoSuchAlgorithmException e) {
      throw new SignatureException(
        "NoSuchAlgorithmException:" + e.getMessage()
      );
    }
    return new String(Base64.encodeBase64(rawHmac));
  }

  private String md5(String cipherText) {
    try {
      byte[] data = cipherText.getBytes();
      // 信息摘要是安全的单向哈希函数，它接收任意大小的数据，并输出固定长度的哈希值。
      MessageDigest mdInst = MessageDigest.getInstance("MD5");

      // MessageDigest对象通过使用 update方法处理数据， 使用指定的byte数组更新摘要
      mdInst.update(data);

      // 摘要更新之后，通过调用digest（）执行哈希计算，获得密文
      byte[] md = mdInst.digest();

      // 把密文转换成十六进制的字符串形式
      int j = md.length;
      char[] str = new char[j * 2];
      int k = 0;
      for (byte byte0 : md) { // i = 0
        str[k++] = MD5_TABLE[byte0 >>> 4 & 0xf]; // 5
        str[k++] = MD5_TABLE[byte0 & 0xf]; // F
      }
      // 返回经过加密后的字符串
      return new String(str);
    } catch (Exception e) {
      return null;
    }
  }
}
```

### 鉴权结果

如果鉴权失败，则根据不同错误类型返回不同 HTTP Code 状态码，同时携带错误描述信息，详细错误说明如下：

| HTTP Code | 说明 | 错误描述信息 | 解决方法 |
|----|----|----|----|
| 401 | 鉴权参数为空 | Invalid Param, Please check header | 检查是否设置鉴权参数 |
| 401 | 签名参数解析失败 | Signature cannot be verified | 检查签名的各个参数是否有缺失是否正确，特别确认下复制的**secret**是否正确 |
| 401 | 签名校验失败 | Signature required | 签名验证失败，可能原因有很多。 1. 检查 appId、secret 是否正确。 2.检查计算签名的方法是否正确。 3. 检查时间戳是否正确等等 |
| 403 | 时钟偏移校验失败 | Invalid time or time required | 检查服务器时间是否标准，相差 5 分钟以上会报此错误 |
| 405 | 应用无效 | Invalid Signature | 检查该 appId 是否开通授权 |

## 三、基础功能

### 3.1、文档上传

##### 接口描述

上传知识库文档数据，目前支持 txt、md、doc、docx、pdf、xls、xlsx、csv、jpg、jpeg、png、bmp、ppt、pptx 格式，单文件大小不超过 20MB，不超过 100W 字符。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/file/upload
```

##### 请求参数说明

``` text
POST，multipart/form-data
```

<table>
<colgroup>
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
<col style="width: 20%" />
</colgroup>
<thead>
<tr>
<th>字段名</th>
<th>类型</th>
<th>描述</th>
<th>必须</th>
<th>默认值</th>
</tr>
</thead>
<tbody>
<tr>
<td>repoIds</td>
<td>Array</td>
<td>上传后自动加入的知识库 id 列表</td>
<td>N</td>
<td></td>
</tr>
<tr>
<td>file</td>
<td>MultipartFile</td>
<td>文件</td>
<td>N</td>
<td></td>
</tr>
<tr>
<td>url</td>
<td>String</td>
<td>文件 url （文件和文件 url 必须有一个）</td>
<td>N</td>
<td></td>
</tr>
<tr>
<td>fileName</td>
<td>String</td>
<td>文件名称，带后缀。文件用 url 的方式，该字段必传；<br />
传 file 的话，该字段可不传</td>
<td>N</td>
<td></td>
</tr>
<tr>
<td>parseType</td>
<td>String</td>
<td>文件解析类型，<code>AUTO</code>-服务端智能判断是否需要走 OCR；<br />
<code>TEXT</code>-直接读取文件文本内容；<code>OCR</code>-强制走 OCR；目前 OCR 主要对 pdf、word 有效</td>
<td>N</td>
<td>AUTO</td>
</tr>
<tr>
<td>stepByStep</td>
<td>Boolean</td>
<td>是否分步处理，true代表文件上传之后，服务只做了分片，<br />
这时候还不能去问答。需要业务做分片的确认，然后调用【文档向量化】接口，发起切片向量。待向量完成，即可问答。</td>
<td>N</td>
<td>false</td>
</tr>
<tr>
<td>needSummary</td>
<td>Boolean</td>
<td>是否需要生成文章总结</td>
<td>N</td>
<td>true</td>
</tr>
<tr>
<td>callbackUrl</td>
<td>String</td>
<td>文件状态回调地址，文件状态有变动时服务会调用该 url。<br />
调用的时候会带上鉴权头，鉴权方式同【接口鉴权】，业务可根据需要是否做鉴权校验</td>
<td>N</td>
<td></td>
</tr>
<tr>
<td>extend</td>
<td>String</td>
<td>文件拆分扩展字段(转为JSONString)，也可在分步时，单独调用拆分接口重新发起拆分</td>
<td>N</td>
<td></td>
</tr>
<tr>
<td>extend.wikiSplitExtends</td>
<td>Object</td>
<td>WIKI拆分扩展（目前使用此方式）</td>
<td>N</td>
<td></td>
</tr>
<tr>
<td>extend.wikiSplitExtends.chunkSeparators</td>
<td>List</td>
<td>分段分隔符，支持多分隔符，base64编码</td>
<td>N</td>
<td>["DQo="]</td>
</tr>
<tr>
<td>extend.wikiSplitExtends.chunkSize</td>
<td>Int</td>
<td>分段最大长度，超过强行切分，默认2000</td>
<td>N</td>
<td>2000</td>
</tr>
<tr>
<td>extend.wikiSplitExtends.minChunkSize</td>
<td>Int</td>
<td>分段最小长度，小于这个长度的会聚合，默认256</td>
<td>N</td>
<td>256</td>
</tr>
</tbody>
</table>

##### extend说明

| 字段名 | 类型 | 描述 | 必须 | 默认值 |
|----|----|----|----|----|
| wikiSplitExtends | Object | WIKI拆分扩展（目前使用此方式） | N |  |
| wikiSplitExtends.chunkSeparators | List | 分段分隔符，支持多分隔符，base64编码 | N | \["DQo="\] |
| wikiSplitExtends.chunkSize | Int | 分段最大长度，超过强行切分，默认2000 | N | 2000 |
| wikiSplitExtends.minChunkSize | Int | 分段最小长度，小于这个长度的会聚合，默认256 | N | 256 |

##### callbackUrl说明

服务端在文件状态有变化的时候，即会调用该回调地址，调用方式为 - GET: callbackUrl?fileId=xxx&fileStatus=xxx，调用的时候会带上业务appId对应的鉴权头，鉴权方式同【接口鉴权】，业务可根据需要是否做鉴权校验。

| 字段名     | 类型   | 描述     |
|------------|--------|----------|
| fileId     | String | 文件id   |
| fileStatus | String | 文件状态 |

##### 返回参数说明

| 字段名 | 类型 | 描述 |
|----|----|----|
| code | Int | 错误码，成功=0 |
| sid | String | 请求唯一 id，用于问题定位 |
| desc | String | 结果描述 |
| data | Object | 返回结果 |
| data.fileId | String | 返回上传的 fileId |
| data.quantity | Int | 当前文件扣除多少页数使用量，PDF/DOC按自然页计算，若每页字数到2000也计算一页 |
| data.parseType | String | 文件解析使用的类型，TEXT/OCR；TEXT代表直接读文本内容，OCR代表走了OCR解析 |

##### 返回参数示例

``` json
{
  "flag": true,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "code": 0,
  "desc": null,
  "data": {
    "quantity": "12",
    "parseType": "TEXT",
    "fileId": "24c4109a57944997bc6b82661243ef67"
  }
}
```

### 3.2、文档状态查询

##### 接口描述

查询文件状态，文件从上传到可问答，经历的状态如下（按顺序）：uploaded-已上传，texted-已文本化，ocring-对文档OCR识别中，spliting-切分中，splited-文本已切分，vectoring-向量中，vectored-已向量化（该状态时可问答），failed-失败。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/file/status
```

##### 请求参数说明

``` text
POST，application/form-data
```

| 字段名  | 类型   | 描述                                       | 必须 | 默认值 |
|---------|--------|--------------------------------------------|------|--------|
| fileIds | String | 上传的文件id列表，多个文档id用英文逗号分割 | Y    |        |

##### 返回参数说明

<table>
<colgroup>
<col style="width: 33%" />
<col style="width: 33%" />
<col style="width: 33%" />
</colgroup>
<thead>
<tr>
<th>字段名</th>
<th>类型</th>
<th>描述</th>
</tr>
</thead>
<tbody>
<tr>
<td>code</td>
<td>Int</td>
<td>错误码，成功=0</td>
</tr>
<tr>
<td>sid</td>
<td>String</td>
<td>请求唯一 id，用于问题定位</td>
</tr>
<tr>
<td>desc</td>
<td>String</td>
<td>结果描述</td>
</tr>
<tr>
<td>data</td>
<td>Array</td>
<td>返回结果</td>
</tr>
<tr>
<td>data.fileId</td>
<td>String</td>
<td>文件id</td>
</tr>
<tr>
<td>data.fileStatus</td>
<td>String</td>
<td>文件状态uploaded-已上传，texted-已文本化，spliting-切分中，splited-文本已切分，<br />
vectoring-向量中，vectored-已向量化，failed-失败</td>
</tr>
</tbody>
</table>

##### 返回参数示例

``` json
{
  "code":0,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "desc":"成功",
  "data":[
    {
      "fileId":"123",
      "fileStatus":"uploaded"
    }
  ]
}
```

### 3.3、文档问答

##### 接口描述

对文档/知识库进行问答，使用 HTTP SSE 流式返回。

注：仅文档状态为 `vectored` 的文件才可以进行问答。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v2/chat
```

##### 请求参数说明

``` text
SSE POST，application/json
Accept: text/event-stream
```

> 在 HTTP Header 中设置鉴权参数：`appId`、`timeStamp`、`signature`。鉴权生成详情请参照上方[鉴权认证](#%E4%BA%8C%E3%80%81%E9%89%B4%E6%9D%83%E8%AE%A4%E8%AF%81)。

| 字段名 | 类型 | 描述 | 必须 | 默认值 |
|----|----|----|----|----|
| repoIds | Array | 知识库 id 列表；`repoIds`、`fileIds` 必传其一 | N |  |
| fileIds | Array | 文件 id 列表；`repoIds`、`fileIds` 必传其一 | N |  |
| topN | Int | 重排后参与回答的文本段数量 | N | 6 |
| llm | String | 指定大模型版本，不传则使用服务端默认模型 | N |  |
| thinkingOutput | Boolean | 是否输出深度思考内容，仅对支持混合思考的模型生效 | N | false |
| messages | Array | 问答内容列表，按时间正序，最后一条为最新提问 | Y |  |
| messages.role | String | user 表示是用户的问题，assistant 表示 AI 的回复 | Y |  |
| messages.content | String | 用户和 AI 的对话内容 | Y |  |
| chatExtends | Object | 大模型对话自定义扩展字段 | N |  |
| chatExtends.retrievalFilterPolicy | String | 检索过滤级别：`STRICT`-严格；`REGULAR`-正常；`LENIENT`-宽松；`OFF`-关闭。越严格，被过滤掉的文本片段越多 | N | REGULAR |
| chatExtends.wikiPromptTpl | String | wiki 大模型问答要求模板 | N | 根据知识库内容回答用户的问题 |
| chatExtends.temperature | Float | 大模型问答时的温度，取值范围 (0，1\] ，temperature 越大，大模型回答随机度越高 | N |  |
| chatExtends.outputType | String | 输出类型：`plain`-文本输出；`multi`-图文输出 | N | plain |

##### 请求参数示例

``` json
{
  "chatExtends": {
    "wikiPromptTpl": "请根据以上内容回答用户的问题",
    "retrievalFilterPolicy": "REGULAR",
    "temperature": 0.2
  },
  "fileIds": ["8b1b17171212121212114fd0806"],
  "messages": [
    {
      "role": "user",
      "content": "如何理赔"
    },
    {
      "role": "assistant",
      "content": "您好，根据您提供的信息，理赔操作指引如下：\n\n1. 登录小程序，点击“理赔申请”。\n2. 选择对应保单。\n3. 上传理赔相关资料。\n4. 填写发票总金额。\n5. 填写银行账户，需精确到支行。\n6. 点击“提交”成功后，返回“理赔服务”界面，点选“理赔查询”，查看理赔进度和申请记录。\n7. 如有需要，点击“查看详情”，查看理赔详情和金额。\n\n请注意，如有严重既往症员工还请和HR部门及时报备沟通，如未及时报备，保险公司不承担相关责任。同时，索赔资料不齐全导致延迟赔付等问题也需要注意。"
    },
    {
      "role": "user",
      "content": "家属有什么福利"
    }
  ]
}
```

##### 返回参数说明

SSE 每个数据帧都是一个 JSON 对象。`status=0` 为首帧，`status=1` 为回答中间帧，`status=2` 为回答结束帧，`status=99` 为引用信息帧。

| 参数名 | 类型 | 描述 |
|----|----|----|
| code | Int | 错误码 ，0 标识成功 |
| message | String | 会话错误描述信息 |
| content | String | 回答内容 |
| reasoning_content | String | 深度思考内容，开启 `thinkingOutput` 且模型支持时返回 |
| sid | String | 会话唯一标识 |
| status | Int | 会话状态，取值为\[0,1,2,99\]；0 代表首次结果；1 代表中间结果；2 代表最后一个结果；99 代表引用的文档及文段 |
| fileRefer | String | 文档引用，status=99 的时候返回；结构是个 Map，key=文件 id，value=引用的文段列表（对应 fileTrunks 的 index） |
| qaRefer | Object | QA 引用，`chatExtends.qaRefer=true` 时可能返回 |
| qapairRefer | Object | QA 对引用 |
| fileImages | Object | 图文模式下的文件图片引用，`chatExtends.outputType=multi` 时可能返回 |
| webSearchRefer | Array | 联网搜索引用，启用 `openWebSearch` 且命中联网结果时可能返回 |

若未检索到相关文档内容，接口会返回结束帧并在 `message` 中提示未找到相关内容。可将 `chatExtends.retrievalFilterPolicy` 调整为 `LENIENT` 或 `OFF` 降低过滤强度，也可开启 `spark` 或 `openWebSearch` 做兜底回答。

##### 返回参数实例

- 首帧

``` json
{
  "code": 0,
  "sid": "870b299a48ba46b6b5e4dfbd99fe4497",
  "status": 0
}
```

- 回答中间帧

``` json
{
  "code": 0,
  "content": "和指南。在此之前，我可以为您",
  "sid": "870b299a48ba46b6b5e4dfbd99fe4497",
  "status": 1
}
```

- 引用帧

``` json
{
  "code": 0,
  "fileRefer": "{\"b2de1116b590911111119d0f3dbfc8\":[3,7,8]}",
  "sortedFileRefer": [
    {
      "b2de1116b590911111119d0f3dbfc8": [3, 7, 8]
    }
  ],
  "sid": "870b299a48ba46b6b5e4dfbd99fe4497",
  "status": 99
}
```

- 结束帧

``` json
{
  "code": 0,
  "content": "",
  "sid": "870b299a48ba46b6b5e4dfbd99fe4497",
  "status": 2
}
```

\

## 四、高级功能-文档萃取

### 4.1、提交萃取任务

##### 接口描述

针对单个文档提交萃取任务。 注：只有vectored 状态的文档才可以提交萃取任务。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/qa/extract
```

##### 请求参数说明

``` text
POST，application/json
```

| 字段名 | 类型 | 描述 | 必须 | 默认值 |
|----|----|----|----|----|
| fileId | String | 文件id | Y |  |
| chunkSize | Int | 分片长度，根据这个长度将文件内容分块，然后根据每个分块抽取问题答案 | Y |  |
| numPerChunk | Int | 每个分片问题数（通过改该值限制抽取问题数，非100%准确） | Y |  |
| answerSize | Int | 答案长度（通过改该值限制答案长度，非100%准确） | N |  |
| topicPreference | Array | 主题偏好 | N |  |
| includeAnswer | bool | 是否包含答案，false的话仅有问题 | N | true |
| notifyUrl | String | 回调地址 | N |  |

##### 请求参数示例

``` json
{
  "fileId": "af0823f307f04efa9ab4615052a2eb04",
  "chunkSize":2000,
  "numPerChunk": 2,
  "answerSize": 100
}
```

##### 响应参数说明

| 字段名 | 类型 | 描述 | 必须 | 默认值 |
|----|----|----|----|----|
| code | Int | 错误码，成功=0 | Y | 0 |
| sid | String | 请求唯一id，用于问题定位 | Y |  |
| desc | String | 结果描述 | Y |  |
| data | String | 当前萃取任务的任务id，后续可根据该任务id获取萃取内容 | Y |  |

##### 响应参数示例

``` json
{
  "code": 0,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "desc": "成功",
  "data": "27805ef975654c01aa069f4e9aad0bb1"
}
```

### 4.2、文件萃取状态查询

##### 接口描述

根据文件id，查询文件的萃取状态。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/qa/extract/status?fileId=xxx
```

##### 请求参数说明

``` text
GET
```

| 字段名 | 类型   | 描述   | 必须 | 默认值 |
|--------|--------|--------|------|--------|
| fileId | String | 文件Id | N    |        |

##### 响应参数说明

| 字段名 | 类型 | 描述 | 必须 | 默认值 |
|----|----|----|----|----|
| code | Int | 错误码，成功=0 | Y | 0 |
| sid | String | 请求唯一id，用于问题定位 | Y |  |
| desc | String | 结果描述 | Y |  |
| data | String | 文件萃取状态，UNSTARTED-未开始、EXTRACTING-萃取中、EXTRACTED-萃取完成、FAILED-萃取失败 | Y |  |

##### 响应参数示例

``` json
{
  "flag": true,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "code": 0,
  "desc": null,
  "data": "EXTRACTED"
}
```

### 4.3、获取萃取结果

##### 接口描述

根据萃取任务id或者文件id，获取萃取结果。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/qa/extract/result?taskId=xxx
```

##### 请求参数说明

``` text
GET
```

| 字段名 | 类型   | 描述                       | 必须 | 默认值 |
|--------|--------|----------------------------|------|--------|
| taskId | String | 任务Id，与fileId必须传一个 | N    |        |
| fileId | String | 文件Id                     | N    |        |

##### 响应参数说明

| 字段名                          | 类型   | 描述                     | 必须 | 默认值 |
|---------------------------------|--------|--------------------------|------|--------|
| code                            | Int    | 错误码，成功=0           | Y    | 0      |
| sid                             | String | 请求唯一id，用于问题定位 | Y    |        |
| desc                            | String | 结果描述                 | Y    |        |
| data                            | array  | 返回结果                 | Y    |        |
| data.id                         | String |                          | Y    |        |
| data.question                   | String | 问题                     | Y    |        |
| data.answer                     | String | 答案                     | Y    |        |
| data.chunkIndexReferences       | String | 问题引用分片索引列表     | Y    |        |
| data.answerChunkIndexReferences | String | 答案引用分片索引列表     | Y    |        |

##### 响应参数示例

``` json
{
  "flag": true,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "code": 0,
  "desc": null,
  "data": [{
    "id": "664d98e4e241e050529c74c7",
    "question": "在《鹧鸪天》中，“殷勤昨夜三更雨，又得浮生一日凉”这句诗的含义是什么？",
    "answer": "在《鹧鸪天》中，“殷勤昨夜三更雨，又得浮生一日凉”这句诗的含义是表达了作者对自然美景的欣赏和对生活的感悟。",
    "chunkIndexReferences": [1,2,3],
    "answerChunkIndexReferences": [1,2,3]
  }]
}
```

### 4.4、QA对应用

##### 接口描述

将问题和答案作为QA对应用至文件或者知识库。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/qa/apply
```

##### 请求参数说明

``` text
POST，application/json
```

| 字段名 | 类型 | 描述 | 必须 | 默认值 |
|----|----|----|----|----|
| fileId | String | 文件id | Y |  |
| repoId | String | 知识库id | Y |  |
| question | String | 问题 | Y |  |
| answer | String | 答案 | Y |  |
| embType | String | 向量类型，Q-仅仅问题做向量、QA-问题和内容一起做向量 | N | QA |

##### 请求参数示例

``` json
{
  "fileId": "af0823f307f04efa9ab4615052a2eb04",
  "repoId": "2e66ae9a1f7443248209d3bf85e89432",
  "question": "《醉落魄（忆别）》中提到‘旧交新贵音书绝’，请问这在表达什么情感或现象？",
  "answer": "《醉落魄（忆别）》中提到的“旧交新贵音书绝”表达了作者对过去友情的怀念和对现今与故友失去联系的感慨。这里的“旧交”指的是老朋友，而“新贵”可能指那些地位上升后改变了态度或生活方式的朋友。",
  "embType": "QA"
}
```

##### 响应参数说明

| 字段名 | 类型   | 描述                             | 必须 | 默认值 |
|--------|--------|----------------------------------|------|--------|
| code   | Int    | 错误码，成功=0                   | Y    | 0      |
| sid    | String | 请求唯一id，用于问题定位         | Y    |        |
| desc   | String | 结果描述                         | Y    |        |
| data   | String | 当前QA对的id，后续更新删除需要用 | Y    |        |

##### 响应参数示例

``` json
{
  "code": 0,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "desc": "成功",
  "data": "5a5f57a52f834ae5b12888ebd282ea0a"
}
```

### 4.5、QA对更新

##### 接口描述

根据QA对id更新QA对。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/qa/apply/update
```

##### 请求参数说明

``` text
POST，application/json
```

| 字段名 | 类型 | 描述 | 必须 | 默认值 |
|----|----|----|----|----|
| id | String | QA对id | Y |  |
| fileId | String | 文件id | Y |  |
| repoId | String | 知识库id | Y |  |
| question | String | 问题 | Y |  |
| answer | String | 答案 | Y |  |
| embType | String | 向量类型，Q-仅仅问题做向量、QA-问题和内容一起做向量 | N | QA |

##### 请求参数示例

``` json
{
  "id": "8df4f13724a443b79612f853f9a8ae7b",
  "fileId": "af0823f307f04efa9ab4615052a2eb04",
  "repoId": "2e66ae9a1f7443248209d3bf85e89432",
  "question": "《醉落魄（忆别）》中提到‘旧交新贵音书绝’，请问这在表达什么情感或现象？",
  "answer": "《醉落魄（忆别）》中提到的“旧交新贵音书绝”表达了作者对过去友情的怀念和对现今与故友失去联系的感慨。这里的“旧交”指的是老朋友，而“新贵”可能指那些地位上升后改变了态度或生活方式的朋友。",
  "embType": "QA"
}
```

##### 响应参数说明

| 字段名 | 类型   | 描述                     | 必须 | 默认值 |
|--------|--------|--------------------------|------|--------|
| code   | Int    | 错误码，成功=0           | Y    | 0      |
| sid    | String | 请求唯一id，用于问题定位 | Y    |        |
| desc   | String | 结果描述                 | Y    |        |

##### 响应参数示例

``` json
{
  "code": 0,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "desc": "成功"
}
```

### 4.6、QA对删除

##### 接口描述

删除采用的QA对。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/qa/apply/delete
```

##### 请求参数说明

``` text
POST，application/form-data
```

| 字段名 | 类型   | 描述                                              | 必须 | 默认值 |
|--------|--------|---------------------------------------------------|------|--------|
| ids    | String | 需要删除的文件id，多个用英文逗号拼接，xxx,aaa,bbb | Y    |        |

##### 响应参数说明

| 字段名 | 类型   | 描述                     | 必须 | 默认值 |
|--------|--------|--------------------------|------|--------|
| code   | Int    | 错误码，成功=0           | Y    | 0      |
| sid    | String | 请求唯一id，用于问题定位 | Y    |        |
| desc   | String | 结果描述                 | Y    |        |

##### 响应参数示例

``` json
{
  "code": 0,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "desc": "成功"
}
```

### 4.7、QA对查询

##### 接口描述

查询文件或者知识库添加的问答对。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/qa/apply/page
```

##### 请求参数说明

``` text
POST，application/json
```

| 字段名      | 类型   | 描述                       | 必须 | 默认值 |
|-------------|--------|----------------------------|------|--------|
| fileId      | String | 文件id，和知识库id必传一个 | N    |        |
| repoId      | String | 知识库id                   | N    |        |
| currentPage | Int    | 当前第几页                 | N    | 1      |
| pageSize    | Int    | 每页几条                   | N    | 10     |

##### 请求参数示例

``` json
{
  "fileId": "af0823f307f04efa9ab4615052a2eb04"
}
```

##### 响应参数说明

| 字段名 | 类型 | 描述 | 必须 | 默认值 |
|----|----|----|----|----|
| code | Int | 错误码，成功=0 | Y | 0 |
| sid | String | 请求唯一id，用于问题定位 | Y |  |
| desc | String | 结果描述 | Y |  |
| data | Object | 分页数据 | Y |  |
| data.total | String | 总数 | Y |  |
| data.rows | Array | 查询列表 | Y |  |
| data.rows.id | String | QA对id | Y |  |
| data.rows.question | String | 问题 | Y |  |
| data.rows.answer | String | 答案 | Y |  |
| data.rows.embType | String | 向量类型，Q-仅仅问题做向量、QA-问题和内容一起做向量 | Y |  |

##### 响应参数示例

``` json
{
  "code": 0,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "desc": "成功",
  "data": {
    "total": 1,
    "rows": [
      {
        "id": "5a5f57a52f834ae5b12888ebd282ea0a",
        "question": "如何理赔？",
        "answer": "请登录小程序提交理赔申请。",
        "embType": "QA"
      }
    ]
  }
}
```

## 五、高级功能-文档处理

### 5.1、发起文档总结

##### 接口描述

针对单个文档发起内容总结/概要。 注：只有 splited、vectoring、vectored 状态的文档才可以发起总结。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/file/summary/start
```

##### 请求参数说明

``` text
POST，application/form-data
```

| 字段名 | 类型   | 描述    | 必须 | 默认值 |
|--------|--------|---------|------|--------|
| fileId | String | 文件 ID | Y    |        |

##### 返回参数示例

``` json
{
  "flag": true,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "code": 0,
  "desc": null,
  "data": null
}
```

##### 返回参数说明

| 字段名 | 类型   | 描述                      |
|--------|--------|---------------------------|
| code   | Int    | 错误码，成功=0            |
| sid    | String | 请求唯一 id，用于问题定位 |
| desc   | String | 结果描述                  |
| data   | Object | 返回结果                  |

### 5.2、获取文档总结信息

##### 接口描述

查询文档总结/概要信息

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/file/summary/query
```

##### 请求参数说明

``` text
POST，application/form-data
```

| 字段名 | 类型   | 描述    | 必须 | 默认值 |
|--------|--------|---------|------|--------|
| fileId | String | 文件 ID | Y    |        |

##### 返回参数示例

``` json
{
  "flag": true,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "code": 0,
  "desc": null,
  "data": null
}
```

##### 返回参数说明

<table>
<colgroup>
<col style="width: 33%" />
<col style="width: 33%" />
<col style="width: 33%" />
</colgroup>
<thead>
<tr>
<th>字段名</th>
<th>类型</th>
<th>描述</th>
</tr>
</thead>
<tbody>
<tr>
<td>code</td>
<td>Int</td>
<td>错误码，成功=0</td>
</tr>
<tr>
<td>sid</td>
<td>String</td>
<td>请求唯一 id，用于问题定位</td>
</tr>
<tr>
<td>desc</td>
<td>String</td>
<td>结果描述</td>
</tr>
<tr>
<td>data</td>
<td>Object</td>
<td>返回结果</td>
</tr>
<tr>
<td>data.summaryStatus</td>
<td>String</td>
<td>文件总结状态，unsummary-未总结 summarying-总结中，<br />
done-总结完成，illegal-内容敏感，failed-总结失败</td>
</tr>
<tr>
<td>data.summary</td>
<td>String</td>
<td>总结内容</td>
</tr>
</tbody>
</table>

### 5.3、文档切分

##### 接口描述

根据切分符对文档进行切分，上传文件之后会做一次切分，若切分效果不满意可调用此方法重新切分。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/file/split
```

##### 请求参数说明

``` text
POST，application/json
```

| 字段名 | 类型 | 描述 | 必须 | 默认值 |
|----|----|----|----|----|
| fileIds | Array | 文件列表 | Y |  |
| isSplitDefault | Boolean | 是否用默认切分策略，如果需要自定义切分符，该值需要设置为false | N | true |
| parseType | String | 解析类型，可选值：`AUTO`、`TEXT`、`OCR` | N | TEXT |
| summaryMode | String | 总结模式，可选值：`MAX`、`SMART` | N | MAX |
| stepByStep | Boolean | 是否分步处理 | N | true |
| wikiSplitExtends | Object | WIKI拆分扩展 | N |  |
| wikiSplitExtends.chunkSeparators | Array | 分段分隔符，支持多分隔符，base64编码 | N | \["DQo="\] |
| wikiSplitExtends.chunkSize | Int | 分段最大长度，超过强行切分 | N | 2000 |
| wikiSplitExtends.minChunkSize | Int | 分段最小长度，小于该值的分段会向下段聚合，直至达到该值 | N | 200 |

##### 请求参数示例

``` json
{
  "splitType": "wiki",
  "isSplitDefault":false,
  "fileIds": [
    "af0823f307f04efa9ab4615052a2eb04"
  ],
  "wikiSplitExtends":{
    "chunkSeparators": ["DQo="],
    "minChunkSize": 100,
    "chunkSize": 2000
  }
}
```

##### 返回参数说明

| 字段名 | 类型   | 描述                      |
|--------|--------|---------------------------|
| code   | Int    | 错误码，成功=0            |
| sid    | String | 请求唯一 id，用于问题定位 |
| desc   | String | 结果描述                  |
| data   | Object | 返回结果                  |

##### 返回参数示例

``` json
{
  "code": 0,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "desc": "成功",
  "data": null
}
```

### 5.4、文档向量化

##### 接口描述

对文档切分的文本块进行向量化操作（embedding），对于文件状态处于splited的文件，可以调用该方法进行向量处理。只有向量化之后的文件才可以发起问答。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/file/embedding
```

##### 请求参数说明

``` text
POST，application/form-data
```

| 字段名  | 类型   | 描述                                       | 必须 | 默认值 |
|---------|--------|--------------------------------------------|------|--------|
| fileIds | String | 上传的文件id列表，多个文档id用英文逗号分割 | Y    |        |

##### 返回参数说明

| 字段名 | 类型   | 描述                      |
|--------|--------|---------------------------|
| code   | Int    | 错误码，成功=0            |
| sid    | String | 请求唯一 id，用于问题定位 |
| desc   | String | 结果描述                  |
| data   | Object | 返回结果                  |

##### 返回参数示例

``` json
{
  "code": 0,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "desc": "成功",
  "data": null
}
```

### 5.5、文档内容相似度检测

##### 接口描述

根据输入的文本，检索拆分后的相关原始文本块。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/vector/search
```

##### 请求参数说明

``` text
POST，application/json
```

| 字段名 | 类型 | 描述 | 必须 | 默认值 |
|----|----|----|----|----|
| repoIds | Array | 知识库 id 列表 | N |  |
| fileIds | Array | 文件id列表，不传，查app下所有文件 | N |  |
| topN | Int | 向量库查询数量 | N | 5 |
| esTopN | Int | 全文检索查询数量 | N | 5 |
| content | String | 用户的问题 | Y |  |
| es | Boolean | 是否启用全文检索 | N | false |
| embedding | Boolean | 是否启用向量检索 | N | true |
| reRank | Boolean | 是否对检索结果重排 | N | false |
| chatExtends | Object | 自定义扩展字段 | N |  |
| chatExtends.retrievalFilterPolicy | String | 检索过滤级别：`STRICT`、`REGULAR`、`LENIENT`、`OFF` | N | REGULAR |
| chatExtends.dataType | String | 数据类型：`wiki`、`qapair`；不传表示查询所有类型 | N |  |

##### 请求参数示例

``` json
{
  "fileIds": [
    "aa9efce4188b4025b6f9a3cd35e6de99"
  ],
  "content": "在哪下二维码",
  "chatExtends":{
    "retrievalFilterPolicy": "REGULAR"
  }
}
```

##### 返回参数说明

| 字段名        | 类型   | 描述                         |
|---------------|--------|------------------------------|
| code          | Int    | 错误码，成功=0               |
| sid           | String | 请求唯一 id，用于问题定位    |
| desc          | String | 结果描述                     |
| data          | Array  | 返回结果                     |
| data.content  | String | wiki的文本分片内容           |
| data.score    | Float  | 查询结果分数                 |
| data.fileId   | String | 文件id，代表属于该文件的文段 |
| data.index    | Int    | 文本分片索引                 |
| data.type     | String | 检索类型，vector-向量检索    |
| data.fileType | String | 文件类型，wiki、qa           |

##### 返回参数示例

``` json
{
  "code":0,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "desc":"成功",
  "data":[
    {
      "content":"xxx",
      "score": 67.5,
      "fileId": "aa9efce4188b4025b6f9a3cd35e6de99"
    }]
}
```

### 5.6、文档分块内容获取

##### 接口描述

获取文件分块内容

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/file/chunks
```

##### 请求参数说明

``` text
POST，application/form-data
```

| 字段名      | 类型    | 描述                 | 必须 | 默认值 |
|-------------|---------|----------------------|------|--------|
| fileId      | String  | 上传的文件id         | Y    |        |
| needContent | Boolean | 是否返回分块正文内容 | N    | true   |

##### 返回参数说明

| 字段名         | 类型   | 描述                      |
|----------------|--------|---------------------------|
| code           | Int    | 错误码，成功=0            |
| sid            | String | 请求唯一 id，用于问题定位 |
| desc           | String | 结果描述                  |
| data           | Array  | 返回结果                  |
| data.dataType  | String | 文件类型 wiki             |
| data.dataIndex | Int    | 分块索引                  |
| data.content   | String | wiki分块内容              |

##### 返回参数示例

``` json
{
  "flag": true,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "code": 0,
  "desc": null,
  "data": [
    {
      "id": "f37203b9d39d4afb8816d30080047695",
      "question": null,
      "dataType": "wiki",
      "dataIndex": 0,
      "content": "名称:智能会议解决方案\n简介:讯飞听见智能会议系统是科大讯飞核心语音技术的集大成者，能将语音实时转成文字，经过个性化订制的标准普通话，转写准确率可达到95%以上，适用于各类会议。\n公司:科大讯飞股份有限公司\n价格:面议\n产品详情:讯飞听见智能会议系统是科大讯飞核心语音技术的集大成者，能将语音实时转成文字，经过个性化订制的标准普通话，转写准确率较高，适用于各类会议。\n链接:https://www.aifuwus.com/onstage/cmddetail?id=59"
    },
    {
      "id": "6567375c79c44f28badd1f0c62794a70",
      "question": null,
      "dataType": "wiki",
      "dataIndex": 1,
      "content": "\r\n名称:服务机器人解决方案\n简介:可提供各种场景不同外观的实体机器人定制及租赁服务，应用于展厅、机场、政务、银行、酒店、商超、医院等公共区域。您留下信息后我们将安排商务经理专人对接。\n公司:科大讯飞股份有限公司\n价格:面议\n产品详情:智能机器人可提供迎宾接待、智能交互、多媒体播放等服务，可同时采集用户线下的“交互式”行为数据。融合线下场景数据、CRM数据和讯飞DMP数据，对目标用户属性、需求偏好、内容消费趋势、潜在需求意图等进行全方位的分析，最终实现深刻理解和预测用户的需求意图。帮助品牌与消费者建立一对一的高效互动，提高营销效率，同时为用户减少信息噪音。\n面对不同行业客户个性化的需求，我们提供包括硬件、软件、云平台、PC端、移动端的完整解决方案，旨在构建一个“硬件+软件+服务+营销”的智能生态圈，致力于让每一个行业享受智慧科技。\n链接:https://www.aifuwus.com/onstage/cmddetail?id=67"
    }
  ]
}
```

### 5.7、文档详情

##### 接口描述

查询文件详情。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/file/info
```

##### 请求参数说明

``` text
POST，application/form-data
```

| 字段名      | 类型    | 描述                           | 必须 | 默认值 |
|-------------|---------|--------------------------------|------|--------|
| fileId      | String  | 上传的文件id                   | Y    |        |
| needContent | Boolean | 是否返回合并后的文件内容与字数 | N    | false  |

##### 返回参数说明

| 字段名 | 类型 | 描述 |
|----|----|----|
| code | Int | 错误码，成功=0 |
| sid | String | 请求唯一 id，用于问题定位 |
| desc | String | 结果描述 |
| data | String | 返回结果 |
| data.fileId | String | 文件id |
| data.fileName | String | 文件名称 |
| data.fileType | String | 文件类型wiki |
| data.fileStatus | String | 文件状态 |
| data.extName | String | 文件后缀 |
| data.quantity | Int | 文件计量数 |
| data.expirationStatus | String | 文件过期状态 active-正常 ，expired-已过期 |
| data.createTime | String | 文件创建时间 |
| data.expireTime | Date | 文件过期时间，pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8" |

##### 返回参数示例

``` json
{
  "flag": true,
  "code": 0,
  "desc": null,
  "data": {
    "fileId": "b0862da4c91147209434023c48665957",
    "fileName": "《科大讯飞文档知识库产品说明书》.pdf",
    "extName": "pdf",
    "fileType": "wiki",
    "fileStatus": "vectored",
    "quantity": 40,
    "createTime": "2024-01-10 09:50:19",
    "expireTime": "2024-04-09 23:59:59",
    "expirationStatus": "active"
  },
  "sid": "e01f951b14bb427286bbf6048e816745"
}
```

### 5.8、文档列表

##### 接口描述

查询appId下的文件列表

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/file/list
```

##### 请求参数说明

``` text
POST，application/json
```

| 字段名      | 类型   | 描述               | 必须 | 默认值 |
|-------------|--------|--------------------|------|--------|
| fileName    | String | 文件名称，模糊查询 | N    |        |
| extName     | String | 文件后缀           | N    |        |
| fileStatus  | String | 文件状态           | N    |        |
| currentPage | Int    | 查询第几页         | N    | 1      |
| pageSize    | Int    | 每页多少文件       | N    | 20     |

##### 请求参数示例

``` json
{
  "fileName": "产品白皮书",
  "extName": "pdf",
  "currentPage": 1,
  "pageSize": 10
}
```

##### 返回参数说明

| 字段名 | 类型 | 描述 |
|----|----|----|
| code | Int | 错误码，成功=0 |
| sid | String | 请求唯一 id，用于问题定位 |
| desc | String | 结果描述 |
| data | Array | 返回结果 |
| data.fileId | String | 文件id |
| data.fileName | String | 文件名称 |
| data.fileType | String | 文件类型wiki、qa |
| data.fileStatus | String | 文件状态 |
| data.extName | String | 文件后缀 |
| data.quantity | Int | 文件计量数 |
| data.expirationStatus | String | 文件过期状态 active-正常 ，expired-已过期 |
| data.createTime | String | 文件创建时间 |
| data.expireTime | Date | 文件过期时间，pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8" |

##### 返回参数示例

``` json
{
  "flag": true,
  "code": 0,
  "desc": null,
  "data": {
    "total": 67,
    "rows": [
      {
        "fileId": "b59b99d4dbc34157b40d2106a32414ac",
        "fileName": "SFU实时音视频产品白皮书_v1.0.pdf",
        "extName": "pdf",
        "fileType": "wiki",
        "fileStatus": "splited",
        "quantity": 24,
        "createTime": "2024-01-11 19:19:35",
        "expireTime": "2024-04-10 23:59:59",
        "expirationStatus": "active"
      },
      {
        "fileId": "91d4cd682c3f4314b3642fb4d45336f8",
        "fileName": "AI中台产品白皮书_V1.0.pdf",
        "extName": "pdf",
        "fileType": "wiki",
        "fileStatus": "vectored",
        "quantity": 24,
        "createTime": "2023-11-14 18:53:14",
        "expireTime": "2024-02-12 23:59:59",
        "expirationStatus": "expired"
      }
    ]
  },
  "sid": "1a4000e8e1ae4edfbf29c0f63b391161"
}
```

### 5.9、文档删除

##### 接口描述

删除文档，该操作会删除文件向量等相关信息。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/file/del
```

##### 请求参数说明

``` text
POST，application/form-data
```

| 字段名  | 类型   | 描述                                       | 必须 | 默认值 |
|---------|--------|--------------------------------------------|------|--------|
| fileIds | String | 上传的文件id列表，多个文档id用英文逗号分割 | Y    |        |

##### 返回参数说明

| 字段名 | 类型   | 描述                      |
|--------|--------|---------------------------|
| code   | Int    | 错误码，成功=0            |
| sid    | String | 请求唯一 id，用于问题定位 |
| desc   | String | 结果描述                  |

##### 返回参数示例

``` json
{
  "code": 0,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "desc": "成功",
  "data": null
}
```

## 六、高级功能-知识库

### 6.1、知识库创建

##### 接口描述

创建一个新的知识库。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/repo/create
```

##### 请求参数说明

``` text
POST，application/json
```

| 字段名   | 类型   | 描述             | 必须 | 默认值 |
|----------|--------|------------------|------|--------|
| repoName | String | 知识库名称，唯一 | Y    |        |
| repoDesc | String | 知识库简介       | N    |        |
| repoTags | String | 知识库标签       | N    |        |

##### 请求参数实例

``` json
{
  "repoName":  "测试问答知识库",
  "repoDesc":"这是知识库简介",
  "repoTags":  "IT知识问答,AI"
}
```

##### 返回参数说明

| 字段名 | 类型   | 描述                         |
|--------|--------|------------------------------|
| code   | Int    | 错误码，成功=0               |
| sid    | String | 请求唯一 id，用于问题定位    |
| desc   | String | 结果描述                     |
| data   | String | 知识库id，后续知识库操作使用 |

##### 返回参数示例

``` json
{
  "flag": true,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "code": 0,
  "desc": null,
  "data": "24c4109a57944997bc6b82661243ef67"
}
```

### 6.2、知识库添加文件

##### 接口描述

向知识库中添加文件，每次操作最多可添加20个文件进知识库，文件较多时，需要分多次添加。且同一个文件最多可存在于10个不同知识库。 注：仅文档状态为vectored的文件才可以进行问答

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/repo/file/add
```

##### 请求参数说明

``` text
POST，application/json
```

| 字段名  | 类型   | 描述               | 必须 | 默认值 |
|---------|--------|--------------------|------|--------|
| repoId  | String | 知识库id           | Y    |        |
| fileIds | Array  | 文件id列表，最大20 | Y    |        |

##### 请求参数实例

``` json
{
  "repoId": "8b1b1717f6e14ed1bd8647cba4fd0806",
  "fileIds": [
    "5a5f57a52f834ae5b12888ebd282ea0a",
    "3a1668af97864f6ca0060d9eda0ffde4",
    "2e66ae9a1f7443248209d3bf85e89432"
  ]
}
```

##### 返回参数说明

| 字段名          | 类型   | 描述                      |
|-----------------|--------|---------------------------|
| code            | Int    | 错误码，成功=0            |
| sid             | String | 请求唯一 id，用于问题定位 |
| desc            | String | 结果描述                  |
| data            | Object | 返回结果                  |
| data.failedList | Array  | 失败文件id列表            |

##### 返回参数示例

``` json
{
  "flag": true,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "code": 0,
  "desc": null,
  "data": {
    "failedList": [
      "5a5f57a52f834ae5b12888ebd282ea0a"
    ]
  }
}
```

### 6.3、知识库移除文件

##### 接口描述

从知识库中移除文件，一次最多操作20个文件。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/repo/file/remove
```

##### 请求参数说明

``` text
POST，application/json
```

| 字段名  | 类型   | 描述               | 必须 | 默认值 |
|---------|--------|--------------------|------|--------|
| repoId  | String | 知识库id           | Y    |        |
| fileIds | Array  | 文件id列表，最大20 | Y    |        |

##### 请求参数实例

``` json
{
  "repoId": "8b1b1717f6e14ed1bd8647cba4fd0806",
  "fileIds": [
    "5a5f57a52f834ae5b12888ebd282ea0a",
    "3a1668af97864f6ca0060d9eda0ffde4",
    "2e66ae9a1f7443248209d3bf85e89432"
  ]
}
```

##### 返回参数说明

| 字段名          | 类型   | 描述                      |
|-----------------|--------|---------------------------|
| code            | Int    | 错误码，成功=0            |
| sid             | String | 请求唯一 id，用于问题定位 |
| desc            | String | 结果描述                  |
| data            | Object | 返回结果                  |
| data.failedList | Array  | 失败文件id列表            |

##### 返回参数示例

``` json
{
  "flag": true,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "code": 0,
  "desc": null,
  "data": {
    "failedList": [
      "5a5f57a52f834ae5b12888ebd282ea0a"
    ]
  }
}
```

### 6.4、知识库列表

##### 接口描述

查询appid下知识库列表

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/repo/list
```

##### 请求参数说明

``` text
POST，application/json
```

| 字段名      | 类型   | 描述                 | 必须 | 默认值 |
|-------------|--------|----------------------|------|--------|
| repoName    | String | 知识库名称，模糊查询 | N    |        |
| currentPage | Int    | 查询第几页           | N    | 1      |
| pageSize    | Int    | 每页多少文件         | N    | 10     |

##### 请求参数示例

``` json
{
  "repoName": "产品说明",
  "currentPage": 1,
  "pageSize": 10
}
```

##### 返回参数说明

| 字段名 | 类型 | 描述 |
|----|----|----|
| code | Int | 错误码，成功=0 |
| sid | String | 请求唯一 id，用于问题定位 |
| desc | String | 结果描述 |
| data | List | 知识库列表 |
| data.repoId | String | 知识库id |
| data.repoName | String | 知识库名称 |
| data.repoDesc | String | 知识库简介 |
| data.repoTags | String | 知识库tag |
| data.createTime | String | 创建时间，pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8" |

##### 返回参数示例

``` json
{
  "flag": true,
  "code": 0,
  "desc": null,
  "data": [{
    "repoId": "9d1a5beea01e4b4a80f12f66f1ee23b0",
    "repoName": "云平台产品说明",
    "repoDesc": "云平台所有产品说明",
    "repoTags": "",
    "createTime": "2024-02-18 17:47:37"
  }],
  "sid": "0b953bd85e4c4675a8700ba705d69953"
}
```

### 6.5、知识库详情

##### 接口描述

查询知识库详情

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/repo/info
```

##### 请求参数说明

``` text
POST，application/form-data
```

| 字段名 | 类型   | 描述     | 必须 | 默认值 |
|--------|--------|----------|------|--------|
| repoId | String | 知识库id | Y    |        |

##### 返回参数说明

| 字段名 | 类型 | 描述 |
|----|----|----|
| code | Int | 错误码，成功=0 |
| sid | String | 请求唯一 id，用于问题定位 |
| desc | String | 结果描述 |
| data | Object | 返回结果 |
| data.repoId | String | 知识库id |
| data.repoName | String | 知识库名称 |
| data.repoDesc | String | 知识库简介 |
| data.repoTags | String | 知识库tag |
| data.createTime | String | 创建时间，pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8" |

##### 返回参数示例

``` json
{
  "flag": true,
  "code": 0,
  "desc": null,
  "data": [{
    "repoId": "9d1a5beea01e4b4a80f12f66f1ee23b0",
    "repoName": "云平台产品说明",
    "repoDesc": "云平台所有产品说明",
    "repoTags": "",
    "createTime": "2024-02-18 17:47:37"
  }],
  "sid": "0b953bd85e4c4675a8700ba705d69953"
}
```

### 6.6、知识库文件列表

##### 接口描述

查询知识库下所有文件

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/repo/file/list
```

##### 请求参数说明

``` text
POST，application/json
```

| 字段名      | 类型   | 描述               | 必须 | 默认值 |
|-------------|--------|--------------------|------|--------|
| repoId      | String | 知识库id           | Y    |        |
| fileName    | String | 文件名称，模糊查询 | N    |        |
| extName     | String | 文件后缀           | N    |        |
| currentPage | Int    | 查询第几页         | N    | 1      |
| pageSize    | Int    | 每页多少文件       | N    | 20     |

##### 返回参数说明

| 字段名 | 类型 | 描述 |
|----|----|----|
| code | Int | 错误码，成功=0 |
| sid | String | 请求唯一 id，用于问题定位 |
| desc | String | 结果描述 |
| data | Array | 返回结果 |
| data.fileId | String | 文件id |
| data.fileName | String | 文件名称 |
| data.fileType | String | 文件类型wiki、qa |
| data.fileStatus | String | 文件状态 |
| data.extName | String | 文件后缀 |
| data.quantity | Int | 文件计量数 |
| data.expirationStatus | String | 文件过期状态 active-正常 expired-已过期 |
| data.createTime | String | 文件创建时间 |
| data.expireTime | Date | 文件过期时间，pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8" |

### 6.7、知识库删除

##### 接口描述

删除知识库，仅移除知识库和文件的关联关系，不删除文件本身。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/repo/del
```

##### 请求参数说明

``` text
POST，application/form-data
```

| 字段名 | 类型   | 描述     | 必须 | 默认值 |
|--------|--------|----------|------|--------|
| repoId | String | 知识库id | Y    |        |

##### 返回参数说明

| 字段名 | 类型   | 描述                      |
|--------|--------|---------------------------|
| code   | Int    | 错误码，成功=0            |
| sid    | String | 请求唯一 id，用于问题定位 |
| desc   | String | 结果描述                  |

##### 返回参数示例

``` json
{
  "code": 0,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "desc": "成功",
  "data": null
}
```

### 6.8、知识库及文件删除

##### 接口描述

删除知识库，并同时删除该知识库包含的文件及其向量等相关数据。

##### 接口地址

``` text
https://chatdoc.xfyun.cn/openapi/v1/repo/del-with-files
```

##### 请求参数说明

``` text
POST，application/form-data
```

| 字段名 | 类型   | 描述     | 必须 | 默认值 |
|--------|--------|----------|------|--------|
| repoId | String | 知识库id | Y    |        |

##### 返回参数说明

| 字段名 | 类型   | 描述                      |
|--------|--------|---------------------------|
| code   | Int    | 错误码，成功=0            |
| sid    | String | 请求唯一 id，用于问题定位 |
| desc   | String | 结果描述                  |

##### 返回参数示例

``` json
{
  "code": 0,
  "sid": "9746244f046340e2869630e5f6fe8daa",
  "desc": "成功",
  "data": null
}
```

\

## 七、错误码

| 错误码 | 描述                               | 处理方式           |
|--------|------------------------------------|--------------------|
| 10019  | 问答的问题或引用文段可能涉政       | 检查问题或文件内容 |
| 10013  | 问答的问题或引用文段有敏感违规信息 | 检查问题或文件内容 |
| 10014  | 问答的输出有敏感违规信息           | 尝试换个问法       |
| 60001  | 文件类型不对                       | 检查文件           |
| 60002  | 文件大小超限                       | 检查文件           |
| 60003  | 文件上传失败                       | 排查               |
| 60005  | 无文件权限                         | 检查入参           |
| 60011  | 文件字数超限                       | 检查文件           |
| 60012  | 文件无有校字符                     | 检查文件           |
| 60014  | 问答的时候未传入文件 id            | 检查入参           |
| 62001  | 问答的时候，未找到相关文本段       | 检查提问问题       |
| 68003  | 操作太过频繁                       | 自查               |
| 99999  | 内部错误                           | 排查               |

## 八、常见问题

### 文档知识库的主要功能是什么？

> 答：让大模型根据文档内容回答问题，更可创建知识库聚合多文档，一次提问遍历领域知识；文档太多难以通读，快用文档总结，自动总结文档概要，快速了解文档内容等。

### 文档知识库现在支持哪些格式的文档？

> 答：目前支持 Word、PDF、Markdown、txt 格式的文档。

### 文档知识库支持什么应用平台？

> 答：目前支持 WebAPI 应用平台。

在这篇文章中：

- <a href="/doc/spark/ChatDoc-API.html#一、服务介绍" class="sidebar-link" data-full-title="一、服务介绍" data-v-c8d771f8="">一、服务介绍</a>
- <a href="/doc/spark/ChatDoc-API.html#二、鉴权认证" class="sidebar-link" data-full-title="二、鉴权认证" data-v-c8d771f8="">二、鉴权认证</a>
- <a href="/doc/spark/ChatDoc-API.html#三、基础功能" class="sidebar-link" data-full-title="三、基础功能" data-v-c8d771f8="">三、基础功能</a>
- <a href="/doc/spark/ChatDoc-API.html#四、高级功能-文档萃取" class="sidebar-link" data-full-title="四、高级功能-文档萃取" data-v-c8d771f8="">四、高级功能-文档萃取</a>
- <a href="/doc/spark/ChatDoc-API.html#五、高级功能-文档处理" class="sidebar-link" data-full-title="五、高级功能-文档处理" data-v-c8d771f8="">五、高级功能-文档处理</a>
- <a href="/doc/spark/ChatDoc-API.html#六、高级功能-知识库" class="sidebar-link" data-full-title="六、高级功能-知识库" data-v-c8d771f8="">六、高级功能-知识库</a>
- <a href="/doc/spark/ChatDoc-API.html#七、错误码" class="sidebar-link" data-full-title="七、错误码" data-v-c8d771f8="">七、错误码</a>
- <a href="/doc/spark/ChatDoc-API.html#八、常见问题" class="sidebar-link" data-full-title="八、常见问题" data-v-c8d771f8="">八、常见问题</a>
