import React, { useState, useEffect } from 'react';
import { 
  KeyRound, 
  X, 
  RotateCw, 
  AlertCircle, 
  ShieldCheck, 
  ExternalLink,
  Lock,
  Radio,
  LogOut
} from 'lucide-react';
import { AbsUser } from '../types';

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  user: AbsUser | null;
  currentServerUrl: string;
  currentSidecarUrl: string;
  currentUseProxy: boolean;
  onConnect: (params: {
    serverUrl: string;
    sidecarUrl: string;
    useProxy: boolean;
    authMode: 'token' | 'userpass';
    token?: string;
    username?: string;
    password?: string;
    isMock?: boolean;
  }) => Promise<void>;
  onDisconnect: () => void;
}

export const AuthModal: React.FC<AuthModalProps> = ({
  isOpen,
  onClose,
  user,
  currentServerUrl,
  currentSidecarUrl,
  currentUseProxy,
  onConnect,
  onDisconnect,
}) => {
  // Compute default sidecar URL based on client host or standard 13380
  const clientHost = typeof window !== 'undefined' && window.location?.hostname ? window.location.hostname : 'localhost';
  const isCloudHost = clientHost.includes('run.app') || clientHost.includes('webcontainer');
  const defaultLocalSidecar = (!isCloudHost && clientHost !== 'localhost' && clientHost !== '127.0.0.1')
    ? `http://${clientHost}:13380`
    : 'http://localhost:13380';

  const [serverUrl, setServerUrl] = useState(currentServerUrl || 'http://localhost:13378');
  const [sidecarUrl, setSidecarUrl] = useState(
    currentSidecarUrl && !currentSidecarUrl.includes('[your ip:port') ? currentSidecarUrl : defaultLocalSidecar
  );
  const [useProxy, setUseProxy] = useState(currentUseProxy);
  const [authMode, setAuthMode] = useState<'token' | 'userpass'>('token');

  const [token, setToken] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  const [isConnecting, setIsConnecting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    setServerUrl(currentServerUrl || 'http://localhost:13378');
    if (!currentSidecarUrl || currentSidecarUrl.includes('[your ip:port')) {
      setSidecarUrl(defaultLocalSidecar);
    } else {
      setSidecarUrl(currentSidecarUrl);
    }
    setUseProxy(currentUseProxy);
    setErrorMsg(null);
  }, [isOpen, currentServerUrl, currentSidecarUrl, currentUseProxy, defaultLocalSidecar]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);

    if (authMode === 'token' && !token.trim()) {
      setErrorMsg('Please enter an Audiobookshelf API Token or Bearer Token.');
      return;
    }

    if (authMode === 'userpass' && (!username.trim() || !password)) {
      setErrorMsg('Please enter both your Audiobookshelf Username and Password.');
      return;
    }

    setIsConnecting(true);
    try {
      await onConnect({
        serverUrl: serverUrl.trim(),
        sidecarUrl: sidecarUrl.trim(),
        useProxy,
        authMode,
        token: token.trim(),
        username: username.trim(),
        password,
        isMock: false,
      });
      // Clear sensitive unencrypted temporary inputs from state
      setPassword('');
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Authentication failed';
      setErrorMsg(msg);
    } finally {
      setIsConnecting(false);
    }
  };

  const handleMockConnect = async () => {
    setErrorMsg(null);
    setIsConnecting(true);
    try {
      await onConnect({
        serverUrl,
        sidecarUrl,
        useProxy,
        authMode: 'token',
        token: 'sample_demo_token',
        isMock: true,
      });
      onClose();
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to load test session');
    } finally {
      setIsConnecting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/85 backdrop-blur-sm flex items-center justify-center p-4 font-mono">
      <div className="w-full max-w-xl bg-[#0c0c0c] border border-neutral-700 shadow-2xl p-5 sm:p-6 relative overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        
        {/* Header */}
        <div className="flex items-start justify-between pb-4 border-b border-neutral-800">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 bg-neutral-900 border border-neutral-700 flex items-center justify-center text-white">
              <KeyRound className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-white tracking-tight uppercase">
                {user ? 'Change Audiobookshelf User' : 'Connect to Audiobookshelf'}
              </h2>
              <p className="text-[11px] text-neutral-400 mt-0.5">
                Backend app for the bookmarks you create on ABS Mobile app.
              </p>
            </div>
          </div>

          {/* Close button */}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-neutral-500 hover:text-white transition-colors p-1"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Currently Connected Info (if switching user) */}
        {user && (
          <div className="my-4 p-3 bg-neutral-950 border border-neutral-800 flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <Lock className="w-3.5 h-3.5 text-neutral-400" />
              <span className="text-neutral-400">Current User:</span>
              <span className="font-semibold text-white">{user.username}</span>
            </div>
            <button
              type="button"
              onClick={() => {
                onDisconnect();
                onClose();
              }}
              className="text-neutral-400 hover:text-red-400 flex items-center gap-1 text-[11px] underline"
            >
              <LogOut className="w-3 h-3" />
              <span>Disconnect</span>
            </button>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          
          {/* Server & Sidecar URLs */}
          <div className="space-y-3">
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-xs font-medium text-neutral-300">
                  Audiobookshelf Server URL
                </label>
                <div className="flex items-center gap-1.5 text-[10px]">
                  <button
                    type="button"
                    onClick={() => setServerUrl('http://localhost:13378')}
                    className="text-neutral-400 hover:text-white underline cursor-pointer"
                  >
                    Default (http://localhost:13378)
                  </button>
                </div>
              </div>
              <input
                type="url"
                required
                value={serverUrl}
                onChange={(e) => setServerUrl(e.target.value)}
                placeholder="http://localhost:13378 or https://abs.yourdomain.com"
                className="w-full bg-[#181818] border border-neutral-700 hover:border-neutral-500 focus:border-neutral-300 focus:bg-[#202020] text-white px-3 py-2 text-xs focus:outline-none transition-colors font-mono"
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-xs font-medium text-neutral-300">
                  FastAPI Sidecar Service URL
                </label>
                <div className="flex items-center gap-1.5 text-[10px]">
                  <button
                    type="button"
                    onClick={() => setSidecarUrl('http://localhost:13380')}
                    className="text-neutral-400 hover:text-white underline cursor-pointer"
                  >
                    Default (13380)
                  </button>
                  {!isCloudHost && clientHost !== 'localhost' && clientHost !== '127.0.0.1' && (
                    <>
                      <span className="text-neutral-600">|</span>
                      <button
                        type="button"
                        onClick={() => setSidecarUrl(`http://${clientHost}:13380`)}
                        className="text-neutral-400 hover:text-white underline cursor-pointer"
                      >
                        Host IP (13380)
                      </button>
                    </>
                  )}
                </div>
              </div>
              <input
                type="url"
                required
                value={sidecarUrl}
                onChange={(e) => setSidecarUrl(e.target.value)}
                placeholder="http://localhost:13380"
                className="w-full bg-[#181818] border border-neutral-700 hover:border-neutral-500 focus:border-neutral-300 focus:bg-[#202020] text-white px-3 py-2 text-xs focus:outline-none transition-colors font-mono"
              />
              <p className="text-[11px] text-neutral-500 mt-1">
                Default port is <span className="text-neutral-300">13380</span> (FastAPI audio clipper & transcription proxy).
              </p>
            </div>
          </div>

          {/* Proxy Option */}
          <div className="p-2.5 bg-[#141414] border border-neutral-800 flex items-center justify-between text-xs">
            <label className="flex items-center gap-2 cursor-pointer text-neutral-300">
              <input
                type="checkbox"
                checked={useProxy}
                onChange={(e) => setUseProxy(e.target.checked)}
                className="accent-white w-3.5 h-3.5 cursor-pointer"
              />
              <span className="font-semibold text-white">Backend Server Proxy</span>
              <span className="text-neutral-500 text-[11px]">(Bypasses browser CORS errors)</span>
            </label>
            <a
              href="https://github.com/raviwarrier/Audiobookshelf-Bookmarks-Extractor#cors-configuration-warning"
              target="_blank"
              rel="noopener noreferrer"
              className="text-neutral-400 hover:text-white flex items-center gap-1 text-[11px] underline"
            >
              <span>Proxy Docs</span>
              <ExternalLink className="w-3 h-3" />
            </a>
          </div>

          {/* Auth Mode Select */}
          <div className="pt-2 border-t border-neutral-800">
            <span className="block text-xs font-medium text-neutral-300 mb-2">
              Authentication Method:
            </span>
            <div className="flex items-center gap-5">
              <label className="flex items-center gap-2 text-xs cursor-pointer">
                <input
                  type="radio"
                  name="modalAuthMode"
                  checked={authMode === 'token'}
                  onChange={() => setAuthMode('token')}
                  className="accent-neutral-200"
                />
                <span className={authMode === 'token' ? 'text-white font-semibold' : 'text-neutral-400'}>
                  API Key / Bearer Token
                </span>
              </label>

              <label className="flex items-center gap-2 text-xs cursor-pointer">
                <input
                  type="radio"
                  name="modalAuthMode"
                  checked={authMode === 'userpass'}
                  onChange={() => setAuthMode('userpass')}
                  className="accent-neutral-200"
                />
                <span className={authMode === 'userpass' ? 'text-white font-semibold' : 'text-neutral-400'}>
                  Username & Password
                </span>
              </label>
            </div>
          </div>

          {/* Inputs depending on mode */}
          {authMode === 'token' ? (
            <div>
              <label className="block text-xs font-medium text-neutral-300 mb-1">
                Audiobookshelf API Token
              </label>
              <input
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="Paste API Token / Bearer Token from ABS Profile"
                className="w-full bg-[#181818] border border-neutral-700 hover:border-neutral-500 focus:border-neutral-300 focus:bg-[#202020] text-white px-3 py-2 text-xs focus:outline-none transition-colors"
              />
              <p className="text-[11px] text-neutral-500 mt-1">
                In Audiobookshelf: Click Profile icon &rarr; API Token &rarr; Copy Token.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-neutral-300 mb-1">
                  Username
                </label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Your ABS username"
                  className="w-full bg-[#181818] border border-neutral-700 hover:border-neutral-500 focus:border-neutral-300 focus:bg-[#202020] text-white px-3 py-2 text-xs focus:outline-none transition-colors"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-neutral-300 mb-1">
                  Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full bg-[#181818] border border-neutral-700 hover:border-neutral-500 focus:border-neutral-300 focus:bg-[#202020] text-white px-3 py-2 text-xs focus:outline-none transition-colors"
                />
              </div>
            </div>
          )}

          {/* Error message */}
          {errorMsg && (
            <div className="p-3 bg-neutral-950 border border-neutral-600 text-xs text-neutral-200 flex items-start gap-2.5">
              <AlertCircle className="w-4 h-4 shrink-0 text-white mt-0.5" />
              <div className="space-y-1">
                <div className="font-semibold text-white">Connection Error</div>
                <div className="text-neutral-300">{errorMsg}</div>
                {errorMsg.includes('CORS') && (
                  <div className="text-neutral-400 text-[11px] pt-1">
                    Tip: Keep &quot;Backend Server Proxy&quot; enabled, or check the{' '}
                    <a
                      href="https://github.com/raviwarrier/Audiobookshelf-Bookmarks-Extractor#cors-configuration-warning"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-white underline hover:text-neutral-300 inline-flex items-center gap-1"
                    >
                      <span>Reverse Proxy & Tunnel guide</span>
                      <ExternalLink className="w-3 h-3" />
                    </a>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Action Buttons */}
          <div className="pt-3 border-t border-neutral-800 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
            <button
              type="button"
              onClick={handleMockConnect}
              disabled={isConnecting}
              className="text-neutral-400 hover:text-white text-xs underline order-2 sm:order-1 transition-colors text-center sm:text-left py-1"
            >
              Explore with Test Demo Session
            </button>

            <div className="flex items-center justify-end gap-2.5 order-1 sm:order-2 shrink-0">
              <button
                type="button"
                onClick={onClose}
                disabled={isConnecting}
                className="px-3 py-2 border border-neutral-700 hover:border-neutral-500 text-xs text-neutral-300 hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isConnecting}
                className="px-4 py-2 bg-neutral-100 text-black hover:bg-white text-xs font-semibold flex items-center justify-center gap-2 disabled:opacity-50 transition-colors shadow-sm shrink-0 whitespace-nowrap"
              >
                {isConnecting ? (
                  <>
                    <RotateCw className="w-3.5 h-3.5 animate-spin" />
                    <span>Connecting...</span>
                  </>
                ) : (
                  <>
                    <Radio className="w-3.5 h-3.5" />
                    <span>Connect & Load Session</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </form>

        {/* Security Footer Note */}
        <div className="mt-4 pt-3 border-t border-neutral-900 flex items-center justify-between text-[11px] text-neutral-500">
          <div className="flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-neutral-400" />
            <span>Zero Persistent Storage: Tokens vanish on refresh/exit</span>
          </div>
          <span>v1.0</span>
        </div>

      </div>
    </div>
  );
};
