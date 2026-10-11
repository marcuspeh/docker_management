import { useState } from "react";
import {
  ApiError,
  Button,
  Input,
  Modal,
  toApiError,
  type CreateRepoBody,
} from "@portal/shared";
import { useCreateRepo } from "../queries";

type FieldErrors = Partial<Record<"name" | "url" | "path", string>>;

export type AddRepoModalProps = {
  open: boolean;
  onClose: () => void;
};

/**
 * Registers a repo. Each API error code lands under the field it belongs to,
 * and Git's own output goes under the URL, since that is where it came from.
 */
export function AddRepoModal({ open, onClose }: AddRepoModalProps) {
  const [form, setForm] = useState<CreateRepoBody>({
    name: "",
    url: "",
    path: "/",
    composeFile: "docker-compose.yml",
  });
  const [errors, setErrors] = useState<FieldErrors>({});
  const createRepo = useCreateRepo();

  const update = (patch: Partial<CreateRepoBody>) => {
    setForm((current) => ({ ...current, ...patch }));
    setErrors({});
  };

  const submit = () => {
    setErrors({});
    createRepo.mutate(
      {
        name: form.name.trim(),
        url: form.url.trim(),
        path: (form.path ?? "/").trim() || "/",
        composeFile: (form.composeFile ?? "").trim() || "docker-compose.yml",
      },
      {
        onSuccess: () => {
          setForm({ name: "", url: "", path: "/", composeFile: "docker-compose.yml" });
          onClose();
        },
        onError: (error) => {
          const apiError = toApiError(error);
          switch (apiError.code) {
            case "INVALID_NAME":
            case "NAME_TAKEN":
              setErrors({ name: apiError.message });
              break;
            case "INVALID_PATH":
              setErrors({ path: apiError.message });
              break;
            case "REPO_UNREACHABLE": {
              const stderr = apiError.detail.stderr;
              setErrors({
                url: typeof stderr === "string" && stderr ? stderr : apiError.message,
              });
              break;
            }
            default:
              if (apiError instanceof ApiError && apiError.field) {
                setErrors({ [apiError.field as keyof FieldErrors]: apiError.message });
              } else {
                setErrors({ url: apiError.message });
              }
          }
        },
      },
    );
  };

  return (
    <Modal
      open={open}
      title="Add Repository"
      description="The portal checks access with git ls-remote and clones on the first deploy."
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={createRepo.isPending}>
            Cancel
          </Button>
          <Button onClick={submit} loading={createRepo.isPending}>
            Add Repository
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Input
          label="Name"
          placeholder="my-service"
          value={form.name}
          error={errors.name}
          onChange={(event) => update({ name: event.target.value })}
        />
        <Input
          label="Git URL"
          placeholder="git@github.com:owner/my-service.git"
          className="font-mono"
          value={form.url}
          error={errors.url}
          onChange={(event) => update({ url: event.target.value })}
        />
        <Input
          label="Compose file location"
          hint="Path to the compose file inside the repository."
          placeholder="/"
          className="font-mono"
          value={form.path ?? "/"}
          error={errors.path}
          onChange={(event) => update({ path: event.target.value })}
        />
        <Input
          label="Compose file name"
          placeholder="docker-compose.yml"
          className="font-mono"
          value={form.composeFile ?? "docker-compose.yml"}
          onChange={(event) => update({ composeFile: event.target.value })}
        />
      </div>
    </Modal>
  );
}