import { h, onMounted, reactive, ref, shallowRef, type Ref } from "vue";
import { useI18n } from "vue-i18n";
import { ElTag } from "element-plus";
import { usePageAuth } from "@/router/utils";
import { isSuccess } from "@/api/types";
import {
  formatPageColumns,
  type OperationProps,
  type PageTableColumn
} from "@/components/RePlusPage";
import { skillGroupApi, type SkillGroup } from "@/api/ticketflow/accounts";

type PageRef = Ref<{ handleGetData?: () => void } | undefined>;

/**
 * 技能组管理：新建与编辑走后端元数据表单（名称、描述、启用），不提供删除；
 * 停用约束（默认组、仍有在职技术员、仍被分类路由使用）由后端 409 给出原因。
 * 技能组列表同时供分类路由下拉使用，列表变化后一并刷新。
 */
export function useSkillGroups(tableRef: PageRef) {
  const { t } = useI18n();
  const api = reactive(skillGroupApi);
  const auth = usePageAuth("TicketFlowSkillGroups", ["categoryRoute"]);
  auth.destroy = false;
  auth.batchDestroy = false;

  const groups = ref<SkillGroup[]>([]);

  async function loadGroups() {
    const res = await skillGroupApi
      .list<SkillGroup>({ page: 1, size: 200 })
      .catch(() => null);
    if (res && isSuccess(res)) groups.value = res.data?.results ?? [];
  }
  onMounted(loadGroups);

  const listColumnsFormat = (columns: PageTableColumn[]) =>
    formatPageColumns(columns, {
      name: column => {
        column["cellRenderer"] = ({ row }) => {
          const group = row as SkillGroup;
          return h("span", { class: "inline-flex items-center gap-2" }, [
            group.name,
            group.is_default
              ? h(ElTag, { size: "small", type: "primary" }, () =>
                  t("ticketflow.skillGroup.default")
                )
              : null
          ]);
        };
      },
      is_active: column => {
        column["cellRenderer"] = ({ row }) => {
          const active = (row as SkillGroup).is_active;
          return h(
            ElTag,
            { size: "small", type: active ? "success" : "info" },
            () =>
              active
                ? t("ticketflow.account.active")
                : t("ticketflow.account.inactive")
          );
        };
      }
    });

  const operationButtonsProps = shallowRef<OperationProps>({});

  /** 列表查询完成（含新建、编辑后的刷新）时同步分类路由用的技能组 */
  function onSearchComplete() {
    void loadGroups();
  }

  return {
    api,
    auth,
    groups,
    listColumnsFormat,
    operationButtonsProps,
    onSearchComplete,
    reload: () => tableRef.value?.handleGetData?.()
  };
}
