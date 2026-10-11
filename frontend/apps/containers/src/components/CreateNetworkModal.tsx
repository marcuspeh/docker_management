import { useState } from "react";
import { Button, Input, Modal, toApiError } from "@portal/shared";
import { useCreateNetwork } from "../queries";

export type CreateNetworkModalProps = {
  open: boolean;
  onClose: () => void;
};

export function CreateNetworkModal({ open, onClose }: CreateNetworkModalProps) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | undefined>();
  const createNetwork = useCreateNetwork();

  const submit = () => {
    setError(undefined);
    createNetwork.mutate(
      { name: name.trim() },
      {
        onSuccess: () => {
          setName("");
          onClose();
        },
        onError: (cause) => {
          // NAME_TAKEN and anything else both belong under the name field:
          // this form has only one input.
          setError(toApiError(cause).message);
        },
      },
    );
  };

  return (
    <Modal
      open={open}
      title="Create Network"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={createNetwork.isPending}>
            Cancel
          </Button>
          <Button onClick={submit} loading={createNetwork.isPending} disabled={!name.trim()}>
            Create
          </Button>
        </>
      }
    >
      <Input
        label="Network name"
        placeholder="my-network"
        className="font-mono"
        value={name}
        error={error}
        onChange={(event) => {
          setName(event.target.value);
          setError(undefined);
        }}
      />
    </Modal>
  );
}