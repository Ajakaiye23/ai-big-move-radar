import { NextResponse, type NextRequest } from 'next/server';
import { createClient } from '@/lib/supabase/server';

/** Where Google and Apple send people back to after they approve. */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get('code');
  const next = searchParams.get('next') ?? '/dashboard';
  const oauthError = searchParams.get('error_description') ?? searchParams.get('error');

  if (oauthError) {
    return NextResponse.redirect(`${origin}/?error=${encodeURIComponent(oauthError)}`);
  }

  if (code) {
    const supabase = await createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      const forwardedHost = request.headers.get('x-forwarded-host');
      const base = process.env.NODE_ENV === 'development' || !forwardedHost
        ? origin
        : `https://${forwardedHost}`;
      return NextResponse.redirect(`${base}${next}`);
    }
    return NextResponse.redirect(`${origin}/?error=${encodeURIComponent(error.message)}`);
  }

  return NextResponse.redirect(`${origin}/?error=${encodeURIComponent('Sign-in was cancelled.')}`);
}
