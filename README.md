# Cos Agent

## 使用

使用请参考 [刻行文档](https://docs.coscene.cn/docs/use-case/common-task)

## 环境

Tested with the following setup:

- python 3.10 with M1 Arm Chips
- a maximum of 500mb video files

## 依赖

```shell
make install
```

## 配置

创建一个文件在~/.config/cos.yaml

```ini
api:
  server_url: https://openapi.coscene.cn
  org_slug: <xxx>

event_code:
  enabled: false

mod:
  name: default
  conf:
    enabled: true

__import__:
  - cos://organizations/current/configMaps/device.collector
  - ~/.config/cos/local.yaml

__reload__:
  reload_interval_in_secs: 60

```

替换上面带尖括号的里的内容

## 本地运行
```shell
$ python3 main.py daemon
```

## 命令行快速安装

具体请参考 [刻行文档](https://docs.coscene.cn/docs/use-case/common-task#%E8%AE%BE%E5%A4%87%E5%AE%89%E8%A3%85-agent)


### 编译单一执行文件
```
make onefile 
```
如在国内的 runner 上需使用清华 PYPI
```
make DOMESTIC=1 onefile
```

## Mod 定制开发

在 `cos/mods/` 下存在两个文件夹，common 和 private，common 为公共模块，private 为私有模块。

common 模块为公共模块，是刻行为所有用户提供的模块，包含规则引擎模式和任务采集模式。
private 模块为私有模块，是客户的定制化模块，存储在刻行的私有仓库，避免泄露。如果需要定制化模块，请联系刻行工程师。

### 模块开发

private 为 git submodule，需要在刻行的私有仓库中开发，开发完成后提交到刻行的私有仓库。
如果您需要本地调试此项目，但是无法访问刻行的私有仓库，可以使用 `git submodule deinit -f .` 命令将 private 模块移除。然后运行即可，但是无法使用私有模块。

如果您有 private 的访问权限，请使用 `git submodule update --init --recursive` 命令初始化 private 模块。

### 提交代码

private 模块的提交请参考刻行的私有仓库的提交规范。⚠️**请勿提交 private 模块的代码到公共仓库。**
