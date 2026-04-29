# chinese-oil-price-data

提供中国成品油调价日历、各省零售价格与价区结构化数据的静态数据仓库。

> [!NOTE]
> 近来油价的变化牵动人心，而其他第三方数据更新延迟很大，因而有了这个项目。每个成品油调价日对应一份价格数据json文件。在每个调价日17点（北京时间）会根据各省的数据更新情况增量更新价格数据json文件。

## 数据说明

| 项目           | json                               |
|:-------------|:-------------------------------------|
| 中国油价调价日数据指针  | data/calendar/latest.json      |
| 中国油价调价日数据      | data/calendar/{year}.json      |
| 中国油价数据指针        | data/prices/latest.json        |
| 中国油价数据            | data/prices/{year}/{date}.json |
| 中国行政区划对应分区数据   | data/regions/regions.json      |
| 中国油价分区数据          | data/regions/{province}.json   |
| 各省发改委地址            | data/sources/provinces.json    |

## 数据来源

> Big thanks to 国家发改委和各省级发改委持续、公开、规范地发布成品油价格公告，为本项目的数据建设提供了可靠基础。

- 国家发改委
  - [国家发展改革委关于进一步完善成品油价格形成机制的通知](https://zfxxgk.ndrc.gov.cn/upload/images/202210/202210239453391.pdf)
- 各省级发改委（按 `province_code` 升序）
  - [北京市发展和改革委员会](https://fgw.beijing.gov.cn/gzdt/tztg/)
  - [天津市发展和改革委员会](https://fzgg.tj.gov.cn/xxfb/tzggx/)
  - [河北省发展和改革委员会](https://hbdrc.hebei.gov.cn/jhlm/jhgggs/)
  - [山西省发展和改革委员会](https://fgw.shanxi.gov.cn/tzgg/)
  - [内蒙古自治区发展和改革委员会](https://fgw.nmg.gov.cn/ywgz/jfgz/cpyjg/)
  - [辽宁省发展和改革委员会](https://fgw.ln.gov.cn/fgw/index/tzgg/index.shtml)
  - [吉林省发展和改革委员会](https://jldrc.jl.gov.cn/zl/zycpjg/)
  - [黑龙江省发展和改革委员会](https://drc.hlj.gov.cn/drc/c111450/common_zfxxgk_fgw.shtml?tab=zdgknr)
  - [上海市发展和改革委员会](https://fgw.sh.gov.cn/fgw_zxxxgk/index.html)
  - [江苏省发展和改革委员会](https://fzggw.jiangsu.gov.cn/col/col284/index.html)
  - [浙江省发展和改革委员会](https://fzggw.zj.gov.cn/col/col1632199/cpyjg/index.html)
  - [安徽省发展和改革委员会](https://fzggw.ah.gov.cn/ywdt/tzgg/index.html)
  - [福建省发展和改革委员会](https://fgw.fujian.gov.cn/zwgk/gsgg/)
  - [江西省发展和改革委员会](https://drc.jiangxi.gov.cn/jxsfzhggwyh/col/col14590/index.html)
  - [山东省发展和改革委员会](http://fgw.shandong.gov.cn/col/col91082/index.html)
  - [河南省发展和改革委员会](https://fgw.henan.gov.cn/xwzx/tzgg/cpydj/)
  - [湖北省发展和改革委员会](https://fgw.hubei.gov.cn/fbjd/zc/zcwj/)
  - [湖南省发展和改革委员会](https://fgw.hunan.gov.cn/fgw/jggb11/newxxgklist.html)
  - [广东省发展和改革委员会](https://drc.gd.gov.cn/ywgg/index.html)
  - [广西壮族自治区发展和改革委员会](http://fgw.gxzf.gov.cn/xwzx/xwfb/)
  - [海南省发展和改革委员会](https://plan.hainan.gov.cn/sfgw/gzdt/list3.shtml)
  - [重庆市发展和改革委员会](https://fzggw.cq.gov.cn/zwgk/zfxxgkml/jgxx/)
  - [四川省发展和改革委员会](https://fgw.sc.gov.cn/sfgw/tzgg/olist.shtml)
  - [贵州省发展和改革委员会](https://fgw.guizhou.gov.cn/fggz/tzgg/)
  - [云南省发展和改革委员会](https://yndrc.yn.gov.cn/html/zhengwugongkai/fadingzhudonggongkaineirong/jiageyushoufei/)
  - [西藏自治区发展和改革委员会](https://drc.xizang.gov.cn/fgdt/jggl/)
  - [陕西省发展和改革委员会](https://sndrc.shaanxi.gov.cn/sy/xwxx/gggg/)
  - [甘肃省发展和改革委员会](https://fzgg.gansu.gov.cn/fzgg/zfdj/list.shtml)
  - [青海省发展和改革委员会](http://fgw.qinghai.gov.cn/xwzx/tzgg/)
  - [宁夏回族自治区发展和改革委员会](https://fzggw.nx.gov.cn/tzgg/)
  - [新疆维吾尔自治区发展和改革委员会](https://xjdrc.xinjiang.gov.cn/xjfgw/c108396/common_list.shtml)

## 本地测试

### 安装依赖
```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

### 命令

```bash
python -m oilprice.cli validate-json
python -m oilprice.cli discover 2026-04-21
python -m oilprice.cli fetch 2026-04-21
python -m oilprice.cli extract 2026-04-21
python -m oilprice.cli price 2026-04-21
python -m oilprice.cli pipeline 2026-04-21
```
