import React, { useState, useCallback, useEffect, useRef } from 'react';
import { Navbar } from './components/Navbar';
import { CaptureView } from './components/CaptureView';
import { SnippetsView } from './components/SnippetsView';
import { AuthModal } from './components/AuthModal';
import { AbsUser, AbsActiveSession, Snippet } from './types';
import { wipeSessionKey } from './lib/crypto';
import { authenticateAbs, fetchActiveSession, formatAuthors } from './lib/absClient';
import { getStoredCredentials, saveStoredCredentials, clearStoredCredentials } from './lib/authStorage';
import { CheckCircle2, X, Bell } from 'lucide-react';

// Helper to determine initial default sidecar URL
function getDefaultSidecarUrl(): string {
  if (typeof window !== 'undefined' && window.location) {
    const host = window.location.hostname;
    if (host && host !== 'localhost' && host !== '127.0.0.1' && !host.includes('run.app') && !host.includes('webcontainer')) {
      return `http://${host}:13380`;
    }
  }
  return 'http://localhost:13380';
}

// Resolves audio URL so that clients accessing externally or through a domain
// stream audio seamlessly via the dashboard server proxy instead of failing on client localhost
export function getPlayableAudioUrl(rawUrl?: string, targetSidecar?: string, proxyEnabled: boolean = true): string {
  if (!rawUrl) return '';
  if (rawUrl.startsWith('http://') || rawUrl.startsWith('https://')) {
    if (typeof window !== 'undefined' && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
      try {
        const parsed = new URL(rawUrl);
        if (parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1') {
          return `${parsed.pathname}${parsed.search}`;
        }
      } catch {}
    }
    return rawUrl;
  }
  const cleanPath = rawUrl.startsWith('/') ? rawUrl : `/${rawUrl}`;
  if (proxyEnabled || !targetSidecar || targetSidecar.includes('localhost') || targetSidecar.includes('127.0.0.1')) {
    return cleanPath;
  }
  return `${targetSidecar.replace(/\/+$/, '')}${cleanPath}`;
}

export function App() {
  const [activeView, setActiveView] = useState<'capture' | 'library'>('capture');
  
  // Connection and Authentication State
  const savedInitial = typeof window !== 'undefined' ? getStoredCredentials() : null;
  const [user, setUser] = useState<AbsUser | null>(null);
  const [activeToken, setActiveToken] = useState<string | null>(null);
  const [serverUrl, setServerUrl] = useState<string>(savedInitial?.serverUrl || 'http://localhost:13378');
  const [sidecarUrl, setSidecarUrl] = useState<string>(savedInitial?.sidecarUrl || getDefaultSidecarUrl());
  const [useProxy, setUseProxy] = useState<boolean>(savedInitial?.useProxy !== undefined ? savedInitial.useProxy : true);

  // Active Listening Session
  const [session, setSession] = useState<AbsActiveSession | null>(null);
  const [isLoadingSession, setIsLoadingSession] = useState<boolean>(false);
  const [sessionError, setSessionError] = useState<string | null>(null);

  // Auth modal control: If credentials were saved previously, keep modal closed while auto-connecting
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(() => {
    if (typeof window === 'undefined') return true;
    const saved = getStoredCredentials();
    return !(saved && (saved.token || (saved.username && saved.password)));
  });

  // Snippets library state
  const [snippets, setSnippets] = useState<Snippet[]>([]);
  const [isLoadingBookmarks, setIsLoadingBookmarks] = useState<boolean>(false);

  // Notification toast for automatic background detection
  const [notification, setNotification] = useState<{ message: string; id: string } | null>(null);
  const lastKnownTimestampRef = useRef<string | null>(null);
  const isSyncingRef = useRef<boolean>(false);

  // Sync user's bookmarks from sidecar's {username}/bookmarks directory
  const syncUserBookmarks = useCallback(async (
    targetSidecar: string,
    token: string,
    username: string,
    proxyEnabled: boolean
  ) => {
    if (isSyncingRef.current) return;
    isSyncingRef.current = true;
    setIsLoadingBookmarks(true);

    try {
      const endpoint = `${targetSidecar.replace(/\/+$/, '')}/api/user/bookmarks`;
      let bookmarksList: any[] = [];

      if (proxyEnabled) {
        const res = await fetch('/api/proxy/abs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            targetUrl: endpoint,
            method: 'GET',
            headers: {
              'Authorization': `Bearer ${token}`,
              'X-ABS-Server-Url': serverUrl,
            }
          })
        });
        const json = await res.json();
        if (json.ok && json.data && Array.isArray(json.data.bookmarks)) {
          bookmarksList = json.data.bookmarks;
        }
      } else {
        const res = await fetch(endpoint, {
          headers: {
            'Authorization': `Bearer ${token}`,
            'X-ABS-Server-Url': serverUrl,
          }
        });
        if (res.ok) {
          const data = await res.json();
          if (data && Array.isArray(data.bookmarks)) {
            bookmarksList = data.bookmarks;
          }
        }
      }

      if (bookmarksList.length > 0) {
        const sidecarBookmarks: Snippet[] = bookmarksList.map((b: any) => ({
          id: b.id || `b-${b.timestamp}`,
          bookTitle: b.book_title,
          author: formatAuthors(b.author, b.authors, b.authorName),
          chapterName: b.chapter,
          timestamp: b.timestamp,
          startTime: b.start_time,
          currentTime: b.current_time,
          libraryItemId: b.library_item_id,
          duration: b.duration,
          audioUrl: getPlayableAudioUrl(b.audio_url, targetSidecar, proxyEnabled),
          transcript: b.transcript,
          markdownContent: `# ${b.book_title}\n\n${b.transcript}`,
          createdAt: b.created_at ? new Date(b.created_at).getTime() : Date.now(),
          username: b.username || username
        }));
        setSnippets(sidecarBookmarks);

        // Update latest known timestamp
        if (sidecarBookmarks[0]?.timestamp) {
          lastKnownTimestampRef.current = sidecarBookmarks[0].timestamp;
        }
      }
    } catch (err) {
      console.warn('Sidecar bookmarks sync notice:', err);
    } finally {
      setIsLoadingBookmarks(false);
      isSyncingRef.current = false;
    }
  }, [serverUrl]);

  // Automatically fetch active listening session once user connects
  const loadActiveSession = useCallback(async (
    targetServer: string,
    token: string,
    proxyEnabled: boolean
  ) => {
    setIsLoadingSession(true);
    setSessionError(null);
    try {
      const active = await fetchActiveSession(targetServer, token, proxyEnabled);
      setSession(active);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Could not fetch active listening session';
      setSessionError(msg);
    } finally {
      setIsLoadingSession(false);
    }
  }, []);

  // Handle connection from Auth Modal
  const handleConnect = async (params: {
    serverUrl: string;
    sidecarUrl: string;
    useProxy: boolean;
    authMode: 'token' | 'userpass';
    token?: string;
    username?: string;
    password?: string;
    isMock?: boolean;
    remember?: boolean;
  }) => {
    setServerUrl(params.serverUrl);
    setSidecarUrl(params.sidecarUrl);
    setUseProxy(params.useProxy);

    if (params.isMock) {
      const mockUser = { id: 'usr_mock', username: 'bookworm_user' };
      setUser(mockUser);
      setActiveToken('mock_token_demo');
      setSession({
        libraryItemId: 'li_sample_project_hail_mary',
        bookTitle: 'Project Hail Mary',
        author: 'Andy Weir',
        chapterName: 'Chapter 04 - Laboratory Discovery',
        currentTime: 1420,
        duration: 36000,
        audioFilePath: '/audiobooks/Andy Weir/Project Hail Mary/Project_Hail_Mary_Part01.m4b',
      });
      setSessionError(null);
      setIsAuthModalOpen(false);
      return;
    }

    const authResult = await authenticateAbs(
      params.serverUrl,
      params.authMode,
      params.token,
      params.username,
      params.password,
      params.useProxy
    );

    setUser(authResult.user);
    setActiveToken(authResult.token);
    setIsAuthModalOpen(false);

    // Save or clear credentials based on the user's "remember" choice
    if (params.remember) {
      saveStoredCredentials({
        serverUrl: params.serverUrl,
        sidecarUrl: params.sidecarUrl,
        useProxy: params.useProxy,
        authMode: params.authMode,
        token: params.authMode === 'token' ? (params.token || authResult.token) : authResult.token,
        username: params.username || authResult.user.username,
        remember: true,
      });
    } else {
      clearStoredCredentials();
    }

    loadActiveSession(params.serverUrl, authResult.token, params.useProxy);
    syncUserBookmarks(params.sidecarUrl, authResult.token, authResult.user.username, params.useProxy);
  };

  // On App Mount: Auto-login from persistent saved credentials if available
  useEffect(() => {
    let isCancelled = false;

    const initializeConnection = async () => {
      let initialServer = 'http://localhost:13378';
      let initialSidecar = getDefaultSidecarUrl();
      let initialProxy = true;

      try {
        const res = await fetch('/api/config');
        const cfg = await res.json();
        if (cfg?.ok) {
          if (cfg.defaultAbsUrl) {
            initialServer = cfg.defaultAbsUrl;
          } else if (cfg.absTargetServer && cfg.absTargetServer !== 'http://audiobookshelf:80') {
            initialServer = cfg.absTargetServer;
          }
          if (cfg.sidecarUrl) {
            initialSidecar = cfg.sidecarUrl;
          }
          if (cfg.useBackendProxy !== undefined) {
            initialProxy = Boolean(cfg.useBackendProxy);
          }
        }
      } catch (err) {
        console.warn('Could not load /api/config, falling back to defaults:', err);
      }

      if (isCancelled) return;

      // 2. Check if user previously saved credentials on this device
      const saved = getStoredCredentials();
      if (saved && (saved.token || (saved.username && saved.password))) {
        try {
          const targetServerToUse = saved.serverUrl || initialServer;
          const targetSidecarToUse = saved.sidecarUrl || initialSidecar;
          const proxyToUse = saved.useProxy !== undefined ? saved.useProxy : initialProxy;
          const authModeToUse = saved.token ? 'token' : saved.authMode;

          setServerUrl(targetServerToUse);
          setSidecarUrl(targetSidecarToUse);
          setUseProxy(proxyToUse);

          const authResult = await authenticateAbs(
            targetServerToUse,
            authModeToUse,
            saved.token,
            saved.username,
            saved.password,
            proxyToUse
          );

          if (isCancelled) return;

          setUser(authResult.user);
          setActiveToken(authResult.token);
          setIsAuthModalOpen(false);

          loadActiveSession(targetServerToUse, authResult.token, proxyToUse);
          syncUserBookmarks(targetSidecarToUse, authResult.token, authResult.user.username, proxyToUse);
        } catch (autoErr) {
          console.warn('Auto-reconnect with saved credentials notice:', autoErr);
          if (!isCancelled) {
            setIsAuthModalOpen(true);
          }
        }
      } else {
        if (!isCancelled) {
          setServerUrl(initialServer);
          setSidecarUrl(initialSidecar);
          setUseProxy(initialProxy);
          setIsAuthModalOpen(true);
        }
      }
    };

    initializeConnection();

    return () => {
      isCancelled = true;
    };
  }, [loadActiveSession, syncUserBookmarks]);

  // Automated Real-Time Background Polling:
  // Detects newly completed manual or intercepted bookmarks and refreshes the snippets view automatically!
  useEffect(() => {
    if (!activeToken || !user) return;

    const interval = setInterval(async () => {
      try {
        const endpoint = `${sidecarUrl.replace(/\/+$/, '')}/api/user/bookmarks/status`;
        let statusData: any = null;

        if (useProxy) {
          const res = await fetch('/api/proxy/abs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              targetUrl: endpoint,
              method: 'GET',
              headers: {
                'Authorization': `Bearer ${activeToken}`,
                'X-ABS-Server-Url': serverUrl,
              }
            })
          });
          const json = await res.json();
          if (json.ok && json.data) {
            statusData = json.data;
          }
        } else {
          const res = await fetch(endpoint, {
            headers: {
              'Authorization': `Bearer ${activeToken}`,
              'X-ABS-Server-Url': serverUrl,
            }
          });
          if (res.ok) {
            statusData = await res.json();
          }
        }

        if (statusData && Array.isArray(statusData.recent) && statusData.recent.length > 0) {
          const latestEvent = statusData.recent[statusData.recent.length - 1];
          if (latestEvent?.timestamp && latestEvent.timestamp !== lastKnownTimestampRef.current) {
            lastKnownTimestampRef.current = latestEvent.timestamp;
            // Trigger automatic sync
            await syncUserBookmarks(sidecarUrl, activeToken, user.username, useProxy);
            
            // Show toast notification
            const methodLabel = latestEvent.extraction_method === 'intercepted' ? 'mobile bookmark' : 'snippet';
            setNotification({
              id: latestEvent.timestamp,
              message: `New ${methodLabel} ready: "${latestEvent.book_title}" (${latestEvent.timestamp})`,
            });
            setTimeout(() => setNotification(null), 6000);
          }
        }
      } catch {
        // Silent catch for background heartbeat
      }
    }, 4000);

    return () => clearInterval(interval);
  }, [activeToken, user, sidecarUrl, serverUrl, useProxy, syncUserBookmarks]);

  // Re-sync session playback position on demand
  const handleRefreshSession = async () => {
    if (!activeToken) return;
    await loadActiveSession(serverUrl, activeToken, useProxy);
  };

  // Wipes in-memory session and clears saved credentials from local storage
  const handleWipeSession = () => {
    setUser(null);
    setActiveToken(null);
    setSession(null);
    setSessionError(null);
    clearStoredCredentials();
    wipeSessionKey();
    setIsAuthModalOpen(true);
  };

  // When a snippet is manually created:
  // 1. Instantly adds it to state
  // 2. Re-syncs full library from server
  // 3. Switches active view to library so user immediately sees the snippet without refreshing!
  const handleSnippetCreated = async (newSnippet: Snippet) => {
    setSnippets((prev) => [newSnippet, ...prev]);
    setNotification({
      id: newSnippet.timestamp,
      message: `Snippet created: "${newSnippet.bookTitle}" (${newSnippet.duration}s)!`,
    });
    setTimeout(() => setNotification(null), 5000);
    
    // Switch to library view immediately
    setActiveView('library');

    // Sync from server in background to ensure all metadata is uniform
    if (activeToken && user) {
      await syncUserBookmarks(sidecarUrl, activeToken, user.username, useProxy);
    }
  };

  const handleDeleteSnippet = async (id: string) => {
    setSnippets((prev) => prev.filter((s) => s.id !== id));

    if (activeToken && sidecarUrl) {
      try {
        const endpoint = `${sidecarUrl.replace(/\/+$/, '')}/api/user/bookmarks/${encodeURIComponent(id)}`;
        if (useProxy) {
          await fetch('/api/proxy/abs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              targetUrl: endpoint,
              method: 'DELETE',
              headers: {
                'Authorization': `Bearer ${activeToken}`,
                'X-ABS-Server-Url': serverUrl,
              }
            })
          });
        } else {
          await fetch(endpoint, {
            method: 'DELETE',
            headers: {
              'Authorization': `Bearer ${activeToken}`,
              'X-ABS-Server-Url': serverUrl,
            }
          });
        }
      } catch (err) {
        console.warn('Notice deleting bookmark from disk:', err);
      }
    }
  };

  return (
    <div className="min-h-screen bg-[#050505] text-neutral-200 font-mono flex flex-col relative">
      
      {/* Real-time Notification Banner for Newly Extracted Bookmarks */}
      {notification && (
        <aside 
          aria-label="New bookmark notification"
          className="fixed top-4 right-4 z-50 bg-[#121212] border border-emerald-500/80 text-white px-4 py-3 shadow-2xl flex items-center gap-3 animate-in fade-in slide-in-from-top-2 duration-300 max-w-md"
        >
          <div className="w-6 h-6 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center shrink-0">
            <CheckCircle2 className="w-4 h-4" />
          </div>
          <div className="text-xs space-y-0.5 flex-1">
            <div className="font-semibold text-emerald-300 flex items-center gap-1.5">
              <Bell className="w-3 h-3" />
              <span>Bookmark Detected & Transcribed</span>
            </div>
            <p className="text-neutral-300 truncate">{notification.message}</p>
          </div>
          <button
            onClick={() => setActiveView('library')}
            className="text-[11px] underline text-neutral-300 hover:text-white px-1.5 py-0.5"
          >
            View
          </button>
          <button
            onClick={() => setNotification(null)}
            className="text-neutral-400 hover:text-white p-1"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </aside>
      )}

      {/* Navigation Header */}
      <Navbar
        activeView={activeView}
        onViewChange={setActiveView}
        user={user}
        snippetCount={snippets.length}
        onOpenAuthModal={() => setIsAuthModalOpen(true)}
        onWipeSession={handleWipeSession}
      />

      {/* Main View Container */}
      <main className="flex-1 max-w-6xl w-full mx-auto p-4 md:p-8">
        {activeView === 'capture' ? (
          <CaptureView
            user={user}
            activeToken={activeToken}
            serverUrl={serverUrl}
            sidecarUrl={sidecarUrl}
            useProxy={useProxy}
            session={session}
            isLoadingSession={isLoadingSession}
            sessionError={sessionError}
            onRefreshSession={handleRefreshSession}
            onOpenAuthModal={() => setIsAuthModalOpen(true)}
            onSnippetCreated={handleSnippetCreated}
            onNavigateToLibrary={() => setActiveView('library')}
            onUseMockSession={() => {
              handleConnect({
                serverUrl,
                sidecarUrl,
                useProxy,
                authMode: 'token',
                token: 'mock_token',
                isMock: true,
              });
            }}
          />
        ) : (
          <SnippetsView
            snippets={snippets}
            user={user}
            activeToken={activeToken}
            serverUrl={serverUrl}
            sidecarUrl={sidecarUrl}
            useProxy={useProxy}
            onDeleteSnippet={handleDeleteSnippet}
            onNavigateToCapture={() => setActiveView('capture')}
            onRefreshSnippets={async () => {
              if (activeToken && user) {
                await syncUserBookmarks(sidecarUrl, activeToken, user.username, useProxy);
              }
            }}
            isLoadingSnippets={isLoadingBookmarks}
          />
        )}
      </main>

      {/* Auth & User Switching Modal */}
      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
        user={user}
        currentServerUrl={serverUrl}
        currentSidecarUrl={sidecarUrl}
        currentUseProxy={useProxy}
        onConnect={handleConnect}
        onDisconnect={handleWipeSession}
      />

      {/* Minimal Footer */}
      <footer className="border-t border-neutral-900 px-6 py-4 text-center text-xs text-neutral-600 font-mono">
        Audiobookshelf Bookmarks Manager • Real-Time Synchronization Enabled
      </footer>
    </div>
  );
}

export default App;
