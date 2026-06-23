import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Terms of Use',
  description:
    'Terms of Use for Metris Lens. The site provides research and informational data derived from public SEC filings and does not constitute investment advice.',
};

const LAST_UPDATED = 'June 23, 2026';

export default function TermsPage() {
  return (
    <div>
      {/* Hero */}
      <div className="px-4 md:px-[120px] pt-14 pb-10">
        <h1 className="font-display text-[52px] md:text-[68px] leading-[1.05] tracking-[-0.03em] text-ink mb-5">
          Terms of Use
        </h1>
        <p className="text-[17px] leading-relaxed text-ink2 max-w-[620px]">
          Please read these terms before using Metris Lens. The site provides
          research information only and is not investment advice.
        </p>
        <p className="text-xs uppercase tracking-[0.12em] text-ink3 mt-5">
          Last updated {LAST_UPDATED}
        </p>
      </div>

      <div className="border-t border-rule" />

      <div className="mx-auto max-w-3xl px-4 sm:px-6 py-12 space-y-12">
        <Section title="Acceptance of terms">
          <p>
            By accessing or using this website (the &quot;Site&quot;), you agree to
            these Terms of Use. If you do not agree, do not use the Site. We may
            update these terms from time to time; continued use after an update
            constitutes acceptance of the revised terms.
          </p>
        </Section>

        <Section title="What Metris Lens provides">
          <p>
            Metris Lens publishes analytics, benchmarks, and position-level indices
            derived from mandatory filings that companies make with the U.S.
            Securities and Exchange Commission (SEC). The data is presented for
            informational and research purposes for a professional audience.
          </p>
        </Section>

        <Section title="Not investment advice">
          <p>
            Nothing on the Site is investment, legal, tax, or accounting advice, and
            nothing on the Site is a recommendation, solicitation, or offer to buy or
            sell any security or to adopt any investment strategy. The indices and
            analytics are not offered as, and should not be relied upon as, a basis
            for any investment decision. Past performance is not indicative of future
            results. You are solely responsible for your own decisions and should
            consult your own professional advisors.
          </p>
        </Section>

        <Section title="Data accuracy and source">
          <p>
            Data is derived from publicly available SEC filings and from systematic
            processing of those filings. While we apply documented, rules-based
            methods and validation, we make no representation or warranty that the
            data is accurate, complete, current, or free of error. Reported fair
            values reflect fund-level mark-to-model estimates, not market transaction
            prices. Coverage gaps and limitations are disclosed in our{' '}
            <Link
              href="/methodology"
              className="text-navy underline underline-offset-2 hover:text-navy/70"
            >
              Methodology
            </Link>{' '}
            and should be reviewed before relying on any figure.
          </p>
        </Section>

        <Section title="Permitted use">
          <p>
            You may view, and reference with attribution, the published content for
            your own internal research and informational use. You may not:
          </p>
          <ul>
            <li>
              scrape, harvest, or systematically extract the Site or its data at scale,
              or place unreasonable load on the infrastructure;
            </li>
            <li>
              redistribute or resell the data as a competing data product or feed
              without permission;
            </li>
            <li>
              misrepresent the source, methodology, or limitations of the data; or
            </li>
            <li>use the Site in violation of any applicable law.</li>
          </ul>
          <p>
            The underlying SEC filings are public records; these restrictions apply to
            our compiled presentation, processing, and derived analytics.
          </p>
        </Section>

        <Section title="Intellectual property">
          <p>
            The Site design, text, methodology documentation, and the compiled and
            derived data sets are the property of Metris, Inc. or its licensors and
            are protected by applicable intellectual property laws. The names
            &quot;Metris&quot; and &quot;Metris Lens&quot; and associated marks may
            not be used without permission.
          </p>
        </Section>

        <Section title="No warranties">
          <p>
            The Site and all content are provided &quot;as is&quot; and &quot;as
            available,&quot; without warranties of any kind, whether express or
            implied, including warranties of merchantability, fitness for a particular
            purpose, accuracy, and non-infringement. We do not warrant that the Site
            will be uninterrupted, secure, or error-free.
          </p>
        </Section>

        <Section title="Limitation of liability">
          <p>
            To the fullest extent permitted by law, Metris, Inc. and its affiliates,
            officers, and contributors will not be liable for any indirect,
            incidental, consequential, special, or punitive damages, or for any loss
            of profits, investment losses, or data, arising from your use of or
            reliance on the Site or its data, even if advised of the possibility of
            such damages.
          </p>
        </Section>

        <Section title="Third-party links">
          <p>
            The Site may link to third-party sites, including the SEC&apos;s EDGAR
            system. We are not responsible for the content, accuracy, or practices of
            those third-party sites.
          </p>
        </Section>

        <Section title="Governing law">
          <p>
            These terms are governed by the laws of the State of Delaware, without
            regard to its conflict-of-laws rules, except where applicable law requires
            otherwise. (Confirm the correct governing jurisdiction for Metris, Inc.
            before relying on this clause.)
          </p>
        </Section>

        <Section title="Contact">
          <p>
            Questions about these terms can be sent to{' '}
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
              href="/privacy"
              className="inline-block px-5 py-3 border border-rule text-ink2 text-sm font-medium hover:bg-surface/50 transition-colors"
            >
              Privacy Policy &rarr;
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
