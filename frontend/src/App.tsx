import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { Layout } from './components/Layout'
import { ProtectedRoute } from './components/ProtectedRoute'
import { LanguageProvider } from './i18n/LanguageContext'
import { LoginPage } from './pages/LoginPage'
import { MfaEnrollPage } from './pages/MfaEnrollPage'
import { HomePage } from './pages/HomePage'
import { UploadPage } from './pages/UploadPage'
import { QueuePage } from './pages/QueuePage'
import { ReviewDetailPage } from './pages/ReviewDetailPage'
import { DuplicateResolvePage } from './pages/DuplicateResolvePage'
import { AuditPage } from './pages/AuditPage'
import { HelpPage } from './pages/HelpPage'
import { MasterDataPage } from './pages/MasterDataPage'
import { MasterRecordDetailPage } from './pages/MasterRecordDetailPage'
import { DashboardPage } from './pages/DashboardPage'
import { EditRequestResolvePage } from './pages/EditRequestResolvePage'

// Page routes below are deliberately singular/renamed (/job, /duplicate,
// /audit-log, /data-quality, /edit-request) where they'd otherwise collide
// with an API path prefix (/jobs, /duplicates, /audit, /dashboard,
// /edit-requests) that the dev proxy and nginx forward to the backend — a
// colliding route would 404 on hard refresh or a direct link.
export default function App() {
  return (
    <BrowserRouter>
      <LanguageProvider>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/mfa-enroll" element={<MfaEnrollPage />} />

            <Route
              element={
                <ProtectedRoute>
                  <Layout />
                </ProtectedRoute>
              }
            >
              <Route path="/" element={<HomePage />} />
              <Route path="/upload" element={<UploadPage />} />
              <Route path="/queue/:domain" element={<QueuePage />} />
              <Route path="/job/:jobId" element={<ReviewDetailPage />} />
              <Route path="/duplicate/:caseId" element={<DuplicateResolvePage />} />
              <Route path="/edit-request/:requestId" element={<EditRequestResolvePage />} />
              <Route path="/help" element={<HelpPage />} />
              <Route
                path="/data-quality"
                element={
                  <ProtectedRoute allowedRoles={['approver', 'admin']}>
                    <DashboardPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/master-data/:domain"
                element={
                  <ProtectedRoute allowedRoles={['approver', 'admin']}>
                    <MasterDataPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/master-data/:domain/:id"
                element={
                  <ProtectedRoute allowedRoles={['approver', 'admin']}>
                    <MasterRecordDetailPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/audit-log"
                element={
                  <ProtectedRoute allowedRoles={['admin']}>
                    <AuditPage />
                  </ProtectedRoute>
                }
              />
            </Route>
          </Routes>
        </AuthProvider>
      </LanguageProvider>
    </BrowserRouter>
  )
}
