import assert from 'node:assert/strict'
import test from 'node:test'
import { createDonorForm, donorFormToPayload } from './donorForm.ts'

test('档案数据可转换为适合各类表单控件的字符串', () => {
  const form = createDonorForm({
    code: 'A2620000',
    status: 'disabled',
    specimen_count: 8,
    serial_no: 21,
    height_cm: 178,
    birth_date: '2000-01-02T00:00:00',
  })

  assert.equal(form.code, 'A2620000')
  assert.equal(form.serial_no, '21')
  assert.equal(form.height_cm, '178')
  assert.equal(form.birth_date, '2000-01-02')
  assert.equal(form.status, 'disabled')
})

test('结构化表单提交时恢复数字和空值类型', () => {
  const payload = donorFormToPayload({
    ...createDonorForm(),
    code: ' A2620001 ',
    serial_no: '22',
    height_cm: '181',
    weight_kg: '72.5',
    ethnicity: ' ',
  })

  assert.equal(payload.code, 'A2620001')
  assert.equal(payload.serial_no, 22)
  assert.equal(payload.height_cm, 181)
  assert.equal(payload.weight_kg, 72.5)
  assert.equal(payload.ethnicity, null)
})
