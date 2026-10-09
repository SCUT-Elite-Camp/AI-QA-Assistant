import { describe, expect, it } from 'vitest'
import { isSensitiveMemoryValue } from '../../server/utils/sensitiveMemoryValue'

describe('sensitive Memory value policy', () => {
  it.each([
    'PASSWORD=correct-horse',
    'my PaSsWd is hidden',
    'contains a SECRET value',
    'Bearer TOKEN value',
    'API   KEY: hidden',
    'PRIVATE KEY: hidden',
    'ACCESS KEY: hidden',
    '银行卡尾号 1234',
    '银行账户 1234',
    '账号是 abc',
    '住址在校内',
    '详细地址在校内',
    '诊断结果',
    '病历内容',
    '疾病信息',
    '药物清单',
    '金融账户信息',
    '11010519491231002X',
    '4111-1111-1111-1111'
  ])('matches the frozen Agent rule: %s', (value) => {
    expect(isSensitiveMemoryValue(value)).toBe(true)
  })

  it('leaves the Agent frozen non-sensitive sample unmatched', () => {
    expect(isSensitiveMemoryValue('讨论课程安排，会议编号为 2026。')).toBe(false)
  })
})
