import { useTranslations } from 'next-intl';

export default function HomePage() {
  const t = useTranslations('home');

  return (
    <main className="container mx-auto flex min-h-screen flex-col items-center justify-center px-4 py-16">
      <div className="w-full max-w-2xl space-y-8 text-center">
        <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
          {t('title')}
        </h1>
        <p className="text-lg text-muted-foreground">{t('subtitle')}</p>
        <div className="flex justify-center gap-4 pt-4">
          <a
            href="/login"
            className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-6 text-sm font-medium text-primary-foreground shadow transition-colors hover:bg-primary/90"
          >
            {t('signIn')}
          </a>
          <a
            href="https://github.com/knowgate/knowgate"
            className="inline-flex h-10 items-center justify-center rounded-md border border-input bg-background px-6 text-sm font-medium shadow-sm transition-colors hover:bg-accent hover:text-accent-foreground"
            target="_blank"
            rel="noreferrer"
          >
            {t('viewSource')}
          </a>
        </div>
        <p className="pt-8 text-xs text-muted-foreground">
          {t('footer')}
        </p>
      </div>
    </main>
  );
}
