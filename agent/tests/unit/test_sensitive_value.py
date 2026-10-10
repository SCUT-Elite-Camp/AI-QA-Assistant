from agent.memory.sensitive_value import isSensitiveMemoryValue


def test_sensitive_value_rules_cover_all_frozen_matchers_and_case_variants() -> None:
    sensitive_values = [
        "PASSWORD=correct-horse",
        "my PaSsWd is hidden",
        "contains a SECRET value",
        "Bearer TOKEN value",
        "API   KEY: hidden",
        "PRIVATE KEY: hidden",
        "ACCESS KEY: hidden",
        "银行卡尾号 1234",
        "银行账户 1234",
        "账号是 abc",
        "住址在校内",
        "详细地址在校内",
        "诊断结果",
        "病历内容",
        "疾病信息",
        "药物清单",
        "金融账户信息",
        "11010519491231002X",
        "4111-1111-1111-1111",
    ]

    assert all(isSensitiveMemoryValue(value) for value in sensitive_values)


def test_sensitive_value_rules_leave_normal_text_unmatched() -> None:
    assert isSensitiveMemoryValue("讨论课程安排，会议编号为 2026。") is False
