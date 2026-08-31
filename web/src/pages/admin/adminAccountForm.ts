export type AdminCreateDraft = {
  username: string
  password: string
  confirmPassword: string
  displayName: string
}

export function adminCreateValidationErrors(values: AdminCreateDraft): string[] {
  const errors: string[] = []
  if (!values.displayName.trim()) errors.push('请填写显示名称')
  if (!/^[A-Za-z0-9_.-]{3,50}$/.test(values.username.trim())) {
    errors.push('登录账号需要 3-50 位字母、数字、点、横线或下划线')
  }
  if (values.password.length < 8) errors.push(`初始密码至少需要 8 位，当前 ${values.password.length} 位`)
  if (values.password !== values.confirmPassword) errors.push('两次输入的密码不一致')
  return errors
}

