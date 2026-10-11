import { Select } from "@portal/shared";
import { useBranches } from "../queries";

export type BranchSelectProps = {
  repoId: string;
  value: string;
  onChange: (branch: string) => void;
  disabled?: boolean;
  error?: string;
};

/**
 * The target branch. Branches come from `git ls-remote --heads`, so this works
 * before the repo has ever been cloned.
 */
export function BranchSelect({
  repoId,
  value,
  onChange,
  disabled,
  error,
}: BranchSelectProps) {
  const { data, isPending, isError } = useBranches(repoId);

  const options = (data?.branches ?? []).map((branch) => ({
    value: branch.name,
    label: branch.name,
  }));

  return (
    <Select
      label="Target Branch"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      disabled={disabled || isPending}
      error={error ?? (isError ? "Could not load branches." : undefined)}
      placeholder={isPending ? "Loading branches..." : "Select a branch"}
      options={options}
    />
  );
}