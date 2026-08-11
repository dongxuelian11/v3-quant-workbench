/**
 * Track N read-only transport input.
 *
 * This shape carries exact relations already authored by canonical owners. It
 * is not a graph schema, identity factory, persistence contract, or authority.
 */
export interface ExactLineageRelationInput {
  readonly sourceExactId: string;
  readonly sourceContentSha256: string;
  readonly targetExactId: string;
  readonly targetContentSha256: string;
  readonly relationType: string;
  readonly bindingRef: string | null;
}
