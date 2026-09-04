import { BrowserRouter } from 'react-router-dom'
import { AdminPage } from './pages/AdminPage'

export default function App() {
  return (
    <BrowserRouter>
      <AdminPage />
    </BrowserRouter>
  )
}
