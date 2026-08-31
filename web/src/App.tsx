import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { AuthProvider } from './context/AuthContext'
import { AboutPage } from './pages/AboutPage'
import { DonorsPage } from './pages/DonorsPage'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import { ForgotPasswordPage } from './pages/ForgotPasswordPage'
import { RegisterPage } from './pages/RegisterPage'
import { UserPage } from './pages/UserPage'
import { AdminPage } from './pages/AdminPage'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<HomePage />} />
            {/* 父子路由保证 /donors ↔ /donors/:code 切换时工作台不卸载 */}
            <Route path="donors" element={<DonorsPage />}>
              <Route index element={null} />
              <Route path=":code" element={null} />
            </Route>
            <Route path="about" element={<AboutPage />} />
            <Route path="user" element={<UserPage />} />
            <Route path="login" element={<LoginPage />} />
            <Route path="forgot-password" element={<ForgotPasswordPage />} />
            <Route path="register" element={<RegisterPage />} />
            <Route path="admin" element={<AdminPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
