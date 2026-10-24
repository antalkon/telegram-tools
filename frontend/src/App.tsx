import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { lazy, Suspense, useEffect, type ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { AppLayout } from './layout/AppLayout'
import { api } from './lib/api'
import Accounts from './pages/Accounts'
import ChannelAnalytics from './pages/ChannelAnalytics'
import Channels from './pages/Channels'
import Monitoring from './pages/Monitoring'
import Overlap from './pages/Overlap'
import Settings from './pages/Settings'
import Users from './pages/Users'
import FoundChannels from './pages/FoundChannels'
import CommentCollector from './pages/CommentCollector'
import ChatIndexer from './pages/ChatIndexer'
import Search from './pages/Search'
import Home from './pages/Home'
import Jobs from './pages/Jobs'
import Login from './pages/Login'

// the graph library is heavy: load these pages on demand
const GraphPage = lazy(() => import('./pages/GraphPage'))
const UserProfile = lazy(() => import('./pages/UserProfile'))

function Spinner() {
  return (
    <div className="flex min-h-dvh items-center justify-center">
      <Loader2 className="size-6 animate-spin text-fg-subtle" aria-label="Загрузка" />
    </div>
  )
}

function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: () => api('/auth/me'), retry: false, staleTime: 60_000 })

  useEffect(() => {
    const onUnauthorized = () => {
      qc.removeQueries({ queryKey: ['me'] })
      navigate('/login', { state: { from: location.pathname } })
    }
    window.addEventListener('tgt:unauthorized', onUnauthorized)
    return () => window.removeEventListener('tgt:unauthorized', onUnauthorized)
  }, [navigate, location.pathname, qc])

  if (me.isLoading) return <Spinner />
  if (me.isError) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Suspense fallback={<Spinner />}>
              <AppLayout />
            </Suspense>
          </RequireAuth>
        }
      >
        <Route index element={<Home />} />
        <Route path="tools/comment-collector" element={<CommentCollector />} />
        <Route path="tools/comment-collector/jobs/:jobId" element={<CommentCollector />} />
        <Route path="tools/chat-indexer" element={<ChatIndexer />} />
        <Route path="tools/chat-indexer/jobs/:jobId" element={<ChatIndexer />} />
        <Route path="search" element={<Search />} />
        <Route path="sources" element={<Navigate to="/channels" replace />} />
        <Route path="users" element={<Users />} />
        <Route path="users/channels" element={<FoundChannels />} />
        <Route path="users/:peerId" element={<UserProfile />} />
        <Route path="channels" element={<Channels />} />
        <Route path="channels/:sourceId" element={<ChannelAnalytics />} />
        <Route path="overlap" element={<Overlap />} />
        <Route path="graph" element={<GraphPage />} />
        <Route path="monitoring" element={<Monitoring />} />
        <Route path="settings" element={<Settings />} />
        <Route path="accounts" element={<Accounts />} />
        <Route path="jobs" element={<Jobs />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
