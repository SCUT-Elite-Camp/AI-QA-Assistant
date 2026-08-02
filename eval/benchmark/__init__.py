"""公开基准评估模块

使用公共检索基准数据集（T2Retrieval、MMarcoRetrieval 等）
对系统检索管道进行多配置 A/B 对比评估。

用法:
    python -m eval.benchmark.run --dataset MMarcoRetrieval --configs baseline-dense,baseline-hybrid,amem-full
"""
