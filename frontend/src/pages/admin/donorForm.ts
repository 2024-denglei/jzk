import type { DonorRow } from './types'

export type DonorFieldKind = 'text' | 'number' | 'date' | 'select' | 'textarea'

export type DonorField = {
  key: string
  label: string
  kind: DonorFieldKind
  placeholder?: string
  options?: string[]
  step?: string
  required?: boolean
  wide?: boolean
}

export type DonorFormSection = {
  title: string
  description: string
  fields: DonorField[]
}

export type DonorFormValues = Record<string, string>

const YES_NO = ['有', '无']

export const DONOR_FORM_SECTIONS: DonorFormSection[] = [
  {
    title: '基础信息',
    description: '档案识别信息、教育背景和库存状态。',
    fields: [
      { key: 'code', label: '捐精人代号', kind: 'text', placeholder: '例如 A2620000', required: true },
      { key: 'serial_no', label: '编号', kind: 'number', placeholder: '请输入数字编号', step: '1' },
      { key: 'abo_blood', label: 'ABO 血型', kind: 'select', options: ['A', 'B', 'AB', 'O'] },
      { key: 'rh_blood', label: 'Rh 血型', kind: 'select', options: ['阳性', '阴性', '+', '-'] },
      { key: 'ethnicity', label: '民族', kind: 'text', placeholder: '例如 汉族' },
      { key: 'hometown', label: '籍贯', kind: 'text', placeholder: '例如 浙江杭州' },
      { key: 'education', label: '学历', kind: 'select', options: ['大专', '本科', '硕士', '博士'] },
      { key: 'occupation', label: '职业', kind: 'text', placeholder: '请输入职业' },
      { key: 'birth_date', label: '出生日期', kind: 'date' },
      { key: 'constellation', label: '星座', kind: 'select', options: ['白羊座', '金牛座', '双子座', '巨蟹座', '狮子座', '处女座', '天秤座', '天蝎座', '射手座', '摩羯座', '水瓶座', '双鱼座'] },
      { key: 'specimen_count', label: '标本库存（管）', kind: 'number', step: '1' },
      { key: 'status', label: '档案状态', kind: 'select', options: ['active', 'disabled'] },
    ],
  },
  {
    title: '身体与外貌',
    description: '数值字段使用数字输入，外貌特征使用可选项。',
    fields: [
      { key: 'height_cm', label: '身高（cm）', kind: 'number', step: '1' },
      { key: 'weight_kg', label: '体重（kg）', kind: 'number', step: '0.1' },
      { key: 'bmi', label: 'BMI', kind: 'number', step: '0.01' },
      { key: 'figure', label: '体型', kind: 'select', options: ['偏瘦', '匀称', '健壮', '偏胖'] },
      { key: 'face_shape', label: '脸型', kind: 'select', options: ['圆形', '椭圆形', '方形', '长形', '菱形'] },
      { key: 'skin_color', label: '肤色', kind: 'select', options: ['偏白', '一般', '小麦'] },
      { key: 'hair_color', label: '发色', kind: 'select', options: ['黑色', '深棕色', '浅棕色'] },
      { key: 'hair_style', label: '发型', kind: 'select', options: ['直发', '卷发', '自然卷'] },
      { key: 'hair_volume', label: '发量', kind: 'select', options: ['多', '中等', '少'] },
      { key: 'eyelid', label: '眼皮', kind: 'select', options: ['单眼皮', '双眼皮', '内双'] },
      { key: 'nose_bridge', label: '鼻梁', kind: 'select', options: ['高', '中等', '低'] },
      { key: 'lip_shape', label: '唇型', kind: 'select', options: ['薄', '适中', '厚'] },
      { key: 'sideburns', label: '络腮胡', kind: 'select', options: YES_NO },
      { key: 'mustache', label: '胡须', kind: 'select', options: YES_NO },
    ],
  },
  {
    title: '性格与爱好',
    description: '记录性格描述及六类兴趣偏好。',
    fields: [
      { key: 'personality', label: '性格', kind: 'textarea', placeholder: '请输入性格特征', wide: true },
      { key: 'hobby_sports', label: '运动健身', kind: 'select', options: YES_NO },
      { key: 'hobby_arts', label: '文化艺术', kind: 'select', options: YES_NO },
      { key: 'hobby_leisure', label: '休闲娱乐', kind: 'select', options: YES_NO },
      { key: 'hobby_travel', label: '旅游度假', kind: 'select', options: YES_NO },
      { key: 'hobby_reading', label: '小说书籍', kind: 'select', options: YES_NO },
      { key: 'hobby_food', label: '美食饮品', kind: 'select', options: YES_NO },
    ],
  },
  {
    title: '健康与家族史',
    description: '健康、生活习惯和遗传相关信息。',
    fields: [
      { key: 'drink_history', label: '喝酒史', kind: 'select', options: ['无', '偶尔', '经常'] },
      { key: 'smoke_history', label: '吸烟史', kind: 'select', options: ['无', '已戒', '偶尔', '经常'] },
      { key: 'personal_disease', label: '个人病史', kind: 'textarea', wide: true },
      { key: 'present_illness', label: '现病史', kind: 'textarea', wide: true },
      { key: 'past_illness', label: '既往病史', kind: 'textarea', wide: true },
      { key: 'surgery_history', label: '手术史', kind: 'textarea', wide: true },
      { key: 'personal_life_hist', label: '个人生活史', kind: 'textarea', wide: true },
      { key: 'partners_6m', label: '近 6 个月性伴侣数', kind: 'text' },
      { key: 'std_history', label: '性传播疾病史', kind: 'textarea', wide: true },
      { key: 'marital_fertility', label: '婚育史', kind: 'textarea', wide: true },
      { key: 'marriage_age', label: '结婚年龄', kind: 'text' },
      { key: 'children_info', label: '生育子女', kind: 'textarea', wide: true },
      { key: 'genetic_history', label: '遗传病史', kind: 'textarea', wide: true },
      { key: 'chromosome_disease', label: '染色体病', kind: 'textarea', wide: true },
      { key: 'monogenic_disease', label: '单基因遗传病', kind: 'textarea', wide: true },
      { key: 'polygenic_disease', label: '多基因遗传病', kind: 'textarea', wide: true },
      { key: 'consanguinity', label: '近亲婚配', kind: 'textarea', wide: true },
    ],
  },
]

const ALL_FIELDS = DONOR_FORM_SECTIONS.flatMap((section) => section.fields)
const INTEGER_FIELDS = new Set(['serial_no', 'height_cm', 'specimen_count'])
const DECIMAL_FIELDS = new Set(['weight_kg', 'bmi'])

export function createDonorForm(row?: DonorRow): DonorFormValues {
  const defaults: DonorFormValues = {
    code: '',
    abo_blood: 'A',
    education: '本科',
    specimen_count: '10',
    status: 'active',
  }
  const values = { ...defaults }
  for (const field of ALL_FIELDS) {
    const value = row?.[field.key]
    if (value !== undefined && value !== null) {
      values[field.key] = field.kind === 'date' ? String(value).slice(0, 10) : String(value)
    } else if (!(field.key in values)) {
      values[field.key] = ''
    }
  }
  return values
}

export function donorFormToPayload(values: DonorFormValues): Record<string, string | number | null> {
  const payload: Record<string, string | number | null> = {}
  for (const field of ALL_FIELDS) {
    const value = (values[field.key] || '').trim()
    if (INTEGER_FIELDS.has(field.key)) {
      payload[field.key] = value === '' ? null : Number.parseInt(value, 10)
    } else if (DECIMAL_FIELDS.has(field.key)) {
      payload[field.key] = value === '' ? null : Number.parseFloat(value)
    } else {
      payload[field.key] = value || null
    }
  }
  payload.code = (values.code || '').trim()
  payload.status = values.status || 'active'
  payload.specimen_count = values.specimen_count === '' ? 10 : Number.parseInt(values.specimen_count, 10)
  return payload
}
