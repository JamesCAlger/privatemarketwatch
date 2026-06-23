import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Privacy Policy',
  description:
    'How Metris Lens handles data and privacy. Metris Lens is a static research site built from public SEC filings and collects minimal personal data.',
};

const LAST_UPDATED = 'June 23, 2026';

export default function PrivacyPage() {
  return (
    <div>
      {/* Hero */}
      <div className="px-4 md:px-[120px] pt-14 pb-10">
        <h1 className="font-display text-[52px] md:text-[68px] leading-[1.05] tracking-[-0.03em] text-ink mb-5">
          Privacy Policy
        </h1>
        <p className="text-[17px] leading-relaxed text-ink2 max-w-[620px]">
          Metris Lens is a static research site built from public SEC filings.
          We collect as little personal data as possible and do not sell it.
        </p>
        <p className="text-xs uppercase tracking-[0.12em] text-ink3 mt-5">
          Last updated {LAST_UPDATED}
        </p>
      </div>

      <div className="border-t border-rule" />

      <div className="mx-auto max-w-3xl px-4 sm:px-6 py-12 space-y-12">
        <Section title="Overview">
          <p>
            Metris Lens is operated by Blue Obsidian Enterprises Limited
            (&quot;Blue Obsidian Enterprises,&quot; &quot;we,&quot; &quot;us&quot;), a
            private limited company registered in England and Wales under company
            number 16340409, with its registered office at 5 Frys Court, London,
            England, SE10 9GG. Blue Obsidian Enterprises is the data controller for
            this site. The site is an informational research platform that
            publishes analytics derived from mandatory filings that companies make
            with the U.S. Securities and Exchange Commission (SEC). It is a
            statically published site: it has no user accounts, no login, and no
            forms that collect personal information.
          </p>
        </Section>

        <Section title="Information we collect">
          <p>We limit data collection to what is necessary to operate the site:</p>
          <ul>
            <li>
              <strong>Server and request logs.</strong> Our hosting provider
              automatically records standard technical information for each request,
              such as IP address, browser user-agent, requested URL, and timestamp.
              This is used for security, abuse prevention, and operating the service.
            </li>
            <li>
              <strong>Analytics (if enabled).</strong> We may use a privacy-respecting,
              aggregate analytics service to understand overall traffic patterns
              (for example, which pages are most visited). Where used, this measures
              aggregate usage and is not used to build advertising profiles of you.
            </li>
            <li>
              <strong>Email you send us.</strong> If you contact one of our published
              email addresses, we receive your message and email address in order to
              respond.
            </li>
          </ul>
          <p>
            We do not knowingly collect names, payment information, or other sensitive
            personal data, because the site does not request it.
          </p>
        </Section>

        <Section title="Cookies">
          <p>
            The core site is static and does not require cookies to function. If an
            analytics tool is enabled, it may set a cookie or use similar storage to
            measure aggregate usage. You can block or delete cookies in your browser
            settings without losing access to the published data.
          </p>
        </Section>

        <Section title="How we use information">
          <p>We use the limited information described above only to:</p>
          <ul>
            <li>deliver and maintain the website;</li>
            <li>protect the site against abuse, scraping, and security threats;</li>
            <li>understand aggregate usage so we can improve the content; and</li>
            <li>respond to messages you send us.</li>
          </ul>
          <p>
            We do not sell personal data, and we do not use it for third-party
            advertising.
          </p>
        </Section>

        <Section title="Third-party services">
          <p>
            We rely on third-party infrastructure providers to operate the site,
            including a hosting and content-delivery provider and, where enabled, an
            analytics provider. These providers process technical request data on our
            behalf under their own terms and privacy policies. The underlying source
            data is obtained from the SEC&apos;s public EDGAR system.
          </p>
        </Section>

        <Section title="Data retention">
          <p>
            Technical logs are retained only as long as needed for security and
            operational purposes, consistent with our providers&apos; standard
            retention periods. Email correspondence is retained as long as needed to
            address your inquiry.
          </p>
        </Section>

        <Section title="Your choices and rights">
          <p>
            Under the UK General Data Protection Regulation (UK GDPR) and other
            applicable law, you may have rights to access, correct, or delete personal
            data we hold about you, to restrict or object to certain processing, and to
            data portability. Because the site collects very little personal data, these
            requests are usually limited to email correspondence and technical logs. To
            make a request, contact us at the address below. If you are unhappy with how
            we handle your data, you also have the right to complain to the UK
            Information Commissioner&apos;s Office (ICO) at ico.org.uk.
          </p>
        </Section>

        <Section title="Children">
          <p>
            The site is intended for a professional and research audience and is not
            directed to children under 13. We do not knowingly collect personal data
            from children.
          </p>
        </Section>

        <Section title="Changes to this policy">
          <p>
            We may update this policy as the site evolves. Material changes will be
            reflected by updating the &quot;Last updated&quot; date above.
          </p>
        </Section>

        <Section title="Contact">
          <p>
            Questions about this policy can be sent to{' '}
            <a
              href="mailto:info@metrislens.com"
              className="text-navy underline underline-offset-2 hover:text-navy/70"
            >
              info@metrislens.com
            </a>
            .
          </p>
        </Section>

        <section>
          <div className="flex flex-wrap gap-4">
            <Link
              href="/terms"
              className="inline-block px-5 py-3 border border-rule text-ink2 text-sm font-medium hover:bg-surface/50 transition-colors"
            >
              Terms of Use &rarr;
            </Link>
            <Link
              href="/"
              className="inline-block px-5 py-3 border border-rule text-ink2 text-sm font-medium hover:bg-surface/50 transition-colors"
            >
              Back to home
            </Link>
          </div>
        </section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="font-display text-[28px] tracking-[-0.015em] text-ink mb-4">
        {title}
      </h2>
      <div className="space-y-4 text-[15px] leading-relaxed text-ink2 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:space-y-2 [&_strong]:text-ink">
        {children}
      </div>
    </section>
  );
}
