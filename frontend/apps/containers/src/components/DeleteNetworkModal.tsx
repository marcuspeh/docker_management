import { AlertTriangle } from "lucide-react";
import { Button, ErrorBanner, Modal, toApiError, type Network } from "@portal/shared";
import { useDeleteNetwork } from "../queries";

export type DeleteNetworkModalProps = {
  network: Network | null;
  onClose: () => void;
};

/**
 * Mounted only while open, so a previous failure cannot survive into the next
 * network's confirmation.
 */
export function DeleteNetworkModal({ network, onClose }: DeleteNetworkModalProps) {
  const deleteNetwork = useDeleteNetwork();

  return (
    <Modal
      open={Boolean(network)}
      title={`Delete ${network?.name ?? "network"}?`}
      onClose={onClose}
      footer={
        <>
          <Button
            variant="secondary"
            onClick={onClose}
            disabled={deleteNetwork.isPending}
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            loading={deleteNetwork.isPending}
            onClick={() =>
              network &&
              deleteNetwork.mutate(network.id, {
                onSuccess: onClose,
              })
            }
          >
            Delete
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex gap-2.5 rounded-md border border-amber-200 bg-amber-50 px-3 py-2.5">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-500" aria-hidden />
          <p className="text-xs text-amber-800">
            Containers currently connected to this network will be disconnected. For
            containers the portal deployed, the attachment is also removed, so a later
            redeploy will not restore it.
          </p>
        </div>
        {deleteNetwork.isError && (
          <ErrorBanner message={toApiError(deleteNetwork.error).message} />
        )}
      </div>
    </Modal>
  );
}